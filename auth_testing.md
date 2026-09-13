# Emergent Google Auth — Testing Playbook (XobaMetrics)

This app supports TWO auth providers that share one user store (`user_id` UUID):
1. Email/password JWT — cookie `access_token` (also returned as `token`).
2. Emergent-managed Google login — cookie `session_token`, stored in `user_sessions`.

`get_current_user` (backend/auth.py) checks `session_token` (cookie → Bearer) first, then the JWT `access_token` (cookie → Bearer).

## Step 1: Create Test User & Session (simulates a completed Google login)
```
mongosh --eval "
use('test_database');
var userId = 'user_gtest' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'g.test.' + Date.now() + '@example.com',
  name: 'Google Test User',
  picture: 'https://via.placeholder.com/150',
  role: 'user',
  auth_provider: 'google',
  beta_approved: true,
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```
NOTE: A Google user has NO workspace until first real login (the /session endpoint auto-creates one). For a manual test, also insert a workspace + creator_profile with `owner_id: userId`, or just verify /auth/me.

## Step 2: Backend API
```
curl -X GET "$REACT_APP_BACKEND_URL/api/auth/me" -H "Authorization: Bearer YOUR_SESSION_TOKEN"
curl -X GET "$REACT_APP_BACKEND_URL/api/workspaces" -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## Step 3: Browser Testing (cookie)
```
await page.context.add_cookies([{
  "name": "session_token", "value": "YOUR_SESSION_TOKEN",
  "domain": "release-race.preview.emergentagent.com", "path": "/",
  "httpOnly": True, "secure": True, "sameSite": "None"
}])
await page.goto("https://release-race.preview.emergentagent.com/dashboard")
```

## Real Google flow (manual, needs a real Google account)
1. Click "Continue with Google" on /login → redirect to https://auth.emergentagent.com/?redirect=<origin>/dashboard
2. Complete Google → lands on <origin>/dashboard#session_id=XXXX
3. AppRouter (useLocation().hash) renders <AuthCallback/> → POST /api/auth/session {session_id} → cookie set → navigate /dashboard.

## Clean test data
```
mongosh --eval "
use('test_database');
db.users.deleteMany({email: /g\\.test\\./});
db.user_sessions.deleteMany({session_token: /test_session/});
"
```

## Success Indicators
- /api/auth/me returns user data (not 401)
- Dashboard loads without redirect to /login
- Callback detection uses useLocation().hash (App.js)
