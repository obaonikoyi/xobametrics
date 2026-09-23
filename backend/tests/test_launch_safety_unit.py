"""Isolated regression tests: no MongoDB, network, OAuth or AI credentials.

Execute with: python -m unittest discover -s backend/tests -p 'test_launch_safety_unit.py'
Functions are compiled from the actual source with imports/route decorators
excluded so these tests run without installing the backend dependencies.
These are not full HTTP/end-to-end deployment tests.
"""
import ast
import asyncio
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_under_test', BACKEND / 'sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def functions(path, names, **dependencies):
    nodes = []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    assert len(nodes) == len(names), 'Requested source functions were not found'
    future = ast.parse('from __future__ import annotations').body
    namespace = dict(HTTPException=HTTPException, Depends=lambda *a: None,
                     get_current_user=lambda: None, File=lambda *a: None,
                     Form=lambda *a: None, sync_mod=sync, **dependencies)
    exec(compile(ast.fix_missing_locations(ast.Module(body=future+nodes, type_ignores=[])), str(path), 'exec'), namespace)
    return SimpleNamespace(**{n: namespace[n] for n in names})


class SyncSafety(unittest.IsolatedAsyncioTestCase):
    async def test_content_does_not_generate_data(self):
        self.assertFalse(await sync.sync_content_item({'id':'real-content'}))

    async def test_connection_never_updates_freshness(self):
        conn = {'id':'real', 'status':'connected', 'last_synced_at':'old'}
        self.assertEqual(await sync.sync_connection(conn), 0)
        self.assertEqual(conn['last_synced_at'], 'old')

    def setUp(self):
        # No live connections exist; the dispatcher may only read.
        self.real_db = sync.db
        sync.db = SimpleNamespace(find=AsyncMock(return_value=[]))

    def tearDown(self):
        sync.db = self.real_db

    async def test_profile_reports_no_sync(self):
        result = await sync.sync_profile('profile')
        self.assertIsNone(result['synced_at'])
        self.assertEqual(result['connections_synced'], 0)
        self.assertEqual(result['snapshots_created'], 0)

    async def test_scheduled_job_is_safe_noop(self):
        self.assertEqual((await sync.run_daily_sync())['snapshots_created'], 0)
        self.assertEqual(vars(sync.db).keys(), {'find'})


class ConnectionSafety(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connections = SimpleNamespace(find_one=AsyncMock(return_value={'id':'c'}), update=AsyncMock(), insert=AsyncMock())
        self.owned = AsyncMock(return_value={'id':'p'})
        self.fn = functions(BACKEND/'routes.py', ['_public_connection','create_connection','reconnect','sync_one_connection','sync_run'],
                            db=self.connections, _owned_profile=self.owned)

    async def test_connect_is_explicitly_unavailable(self):
        with self.assertRaises(HTTPException) as error:
            await self.fn.create_connection(SimpleNamespace(profile_id='p'), {'user_id':'u'})
        self.assertEqual(error.exception.status_code, 501)
        self.connections.insert.assert_not_awaited()
        self.owned.assert_awaited_once_with('p', {'user_id':'u'})

    async def test_reconnect_is_unavailable_without_write(self):
        with self.assertRaises(HTTPException) as error:
            await self.fn.reconnect('c', {'user_id':'u'})
        self.assertEqual(error.exception.status_code, 501)
        self.connections.update.assert_not_awaited()

    async def test_sync_is_unavailable_without_write(self):
        with self.assertRaises(HTTPException) as error:
            await self.fn.sync_one_connection('c', {'user_id':'u'})
        self.assertEqual(error.exception.status_code, 501)
        self.connections.update.assert_not_awaited()

    async def test_missing_or_foreign_connection_is_not_found(self):
        self.connections.find_one.return_value = None
        with self.assertRaises(HTTPException) as error:
            await self.fn.reconnect('foreign', {'user_id':'u'})
        self.assertEqual(error.exception.status_code, 404)
        self.connections.find_one.assert_awaited_once_with('platform_connections', {'id':'foreign','owner_id':'u'})

    async def test_manual_profile_refresh_is_unavailable(self):
        with self.assertRaises(HTTPException) as error:
            await self.fn.sync_run('p', {'user_id':'u'})
        self.assertEqual(error.exception.status_code, 501)

    def test_connections_hide_secrets_and_stub_freshness(self):
        value = self.fn._public_connection({'id':'c','status':'connected','access_token':'secret','refresh_token':'secret','last_synced_at':'now'})
        self.assertNotIn('access_token', value)
        self.assertNotIn('refresh_token', value)
        self.assertEqual(value['status'], 'needs_auth')
        self.assertIsNone(value['last_synced_at'])


class InsightSafety(unittest.IsolatedAsyncioTestCase):
    async def test_route_rejects_wrong_profile_before_ai(self):
        ai = SimpleNamespace(generate_insight=AsyncMock())
        fn = functions(BACKEND/'routes.py', ['ai_insights'],
                       _owned_profile=AsyncMock(), _owned_release=AsyncMock(return_value={'profile_id':'other'}), ai=ai)
        with self.assertRaises(HTTPException) as error:
            await fn.ai_insights(SimpleNamespace(profile_id='mine',release_id='r'), {'user_id':'u'})
        self.assertEqual(error.exception.status_code, 404)
        ai.generate_insight.assert_not_awaited()

    async def test_route_accepts_owned_matching_release(self):
        ai = SimpleNamespace(generate_insight=AsyncMock(return_value={'summary':'ok'}))
        fn = functions(BACKEND/'routes.py', ['ai_insights'],
                       _owned_profile=AsyncMock(), _owned_release=AsyncMock(return_value={'profile_id':'mine'}), ai=ai)
        self.assertEqual(await fn.ai_insights(SimpleNamespace(profile_id='mine',release_id='r'), {'user_id':'u'}), {'summary':'ok'})
        ai.generate_insight.assert_awaited_once_with('mine','r')

    async def test_facts_scope_is_checked_before_metric_reads(self):
        find = AsyncMock(return_value=None)
        analytics = SimpleNamespace(profile_overview=AsyncMock(), release_totals=AsyncMock())
        fn = functions(BACKEND/'ai.py', ['_build_facts'], db=SimpleNamespace(find_one=find), analytics=analytics)
        with self.assertRaises(HTTPException):
            await fn._build_facts('mine','foreign')
        find.assert_awaited_once_with('releases', {'id':'foreign','profile_id':'mine'})
        analytics.profile_overview.assert_not_awaited()
        analytics.release_totals.assert_not_awaited()

    async def get_week(self, points):
        overview = {'totals':{},'release_count':1,'platform_breakdown':[],'releases':[{'id':'r'}], 'top_release':None,'last_synced':None}
        analytics = SimpleNamespace(profile_overview=AsyncMock(return_value=overview), release_race=AsyncMock(return_value={'releases':[{'title':'song','series':points}]}))
        fn = functions(BACKEND/'ai.py', ['_build_facts'], db=None, analytics=analytics)
        return (await fn._build_facts('mine'))['first_week_reach'][0]

    async def test_missing_history_is_unknown_not_zero(self):
        result = await self.get_week([])
        self.assertIsNone(result['observed_day_7_reach'])
        self.assertIsNone(result['latest_observed_reach'])

    async def test_day_three_is_not_labeled_day_seven(self):
        result = await self.get_week([{'day':3,'value':100}])
        self.assertIsNone(result['observed_day_7_reach'])
        self.assertEqual(result['observed_through_day'],3)

    async def test_observed_zero_remains_zero(self):
        self.assertEqual((await self.get_week([{'day':7,'value':0}]))['observed_day_7_reach'],0)


class CsvSafety(unittest.IsolatedAsyncioTestCase):
    def setup_upload(self, row_count=123):
        rows = [{'date':'2026-09-01','views':str(i)} for i in range(row_count)]
        file = SimpleNamespace(filename='export.csv', read=AsyncMock(return_value=b'date,views\n'))
        request = SimpleNamespace(headers={'x-requested-with':'XobaMetrics'})
        files = SimpleNamespace(insert=AsyncMock())
        parser = SimpleNamespace(parse_csv=Mock(return_value=(['date','views'], rows, {})), normalize_rows=Mock(return_value=rows))
        storage = SimpleNamespace(APP_NAME='test', put_object=Mock())
        fn = functions(BACKEND/'routes.py', ['csv_upload'], db=files, csv_import=parser,
                       storage=storage, uuid=__import__('uuid'), _owned_profile=AsyncMock(),
                       new_id=lambda _: 'file', now_iso=lambda:'now', MAX_UPLOAD_BYTES=5*1024*1024, MAX_IMPORT_ROWS=5000)
        return fn.csv_upload, request, file, rows, storage

    async def test_all_rows_survive_upload_not_just_fifty(self):
        upload, request, file, rows, _ = self.setup_upload()
        result = await upload(request, file, 'p', {'user_id':'u'})
        self.assertEqual(len(result['rows']),123)
        self.assertEqual(result['row_count'],123)
        self.assertEqual(len(result['preview']),30)
        file.read.assert_awaited_once_with(5*1024*1024+1)

    async def test_oversized_row_count_is_rejected(self):
        upload, request, file, _, storage = self.setup_upload(5001)
        with self.assertRaises(HTTPException) as error:
            await upload(request,file,'p',{'user_id':'u'})
        self.assertEqual(error.exception.status_code,413)
        storage.put_object.assert_not_called()

    async def test_oversized_file_is_rejected(self):
        upload, request, file, _, storage = self.setup_upload()
        file.read.return_value = b'x' * (5*1024*1024+1)
        with self.assertRaises(HTTPException) as error:
            await upload(request,file,'p',{'user_id':'u'})
        self.assertEqual(error.exception.status_code,413)
        storage.put_object.assert_not_called()


class HealthSafety(unittest.IsolatedAsyncioTestCase):
    async def test_health_is_not_a_claim_of_real_integration(self):
        fn = functions(BACKEND/'server.py',['health'], youtube_configured=lambda: False,
                       soundcloud_configured=lambda: False, google_signin_configured=lambda: False)
        self.assertFalse((await fn.health())['live_integrations_available'])

    async def test_readiness_checks_database(self):
        fetchval = AsyncMock(return_value=1)
        fn = functions(BACKEND/'server.py',['ready'],db=SimpleNamespace(fetchval=fetchval),asyncio=asyncio)
        self.assertEqual((await fn.ready())['status'],'ready')
        fetchval.assert_awaited_once_with('SELECT 1')

    async def test_readiness_does_not_leak_database_errors(self):
        fn = functions(BACKEND/'server.py',['ready'],db=SimpleNamespace(fetchval=AsyncMock(side_effect=RuntimeError('secret'))),asyncio=asyncio)
        with self.assertRaises(HTTPException) as error:
            await fn.ready()
        self.assertEqual(error.exception.status_code,503)
        self.assertNotIn('secret',error.exception.detail)


if __name__ == '__main__':
    unittest.main()
