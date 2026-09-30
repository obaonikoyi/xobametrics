import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import { CONTACT_EMAIL, POLICY_UPDATED } from "@/lib/site";

// Public pages: platform reviewers (Google, TikTok, Meta) open these without
// an account, so they sit outside the signed-in layout.

function Contact() {
  return CONTACT_EMAIL
    ? <a className="text-primary underline" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
    : <span>the contact address on this page</span>;
}

function Page({ title, children }) {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <Link to="/" className="flex items-center gap-2 font-display font-bold">
            <Activity className="h-5 w-5 text-primary" aria-hidden="true" /> XobaMetrics
          </Link>
          <nav className="flex gap-4 text-sm text-muted-foreground">
            <Link to="/privacy" className="hover:text-foreground">Privacy</Link>
            <Link to="/terms" className="hover:text-foreground">Terms</Link>
            <Link to="/data-deletion" className="hover:text-foreground">Data deletion</Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="font-display text-3xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">Last updated {POLICY_UPDATED}</p>
        <div className="legal mt-8 space-y-6 text-sm leading-relaxed text-foreground/90 [&_h2]:mt-8 [&_h2]:font-display [&_h2]:text-lg [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1.5">
          {children}
        </div>
      </main>
    </div>
  );
}

export function Privacy() {
  return (
    <Page title="Privacy Policy">
      <p>
        XobaMetrics (xobametrics.com) helps musicians see their numbers from YouTube, SoundCloud, other platforms
        and distributor reports in one place. This policy explains what we collect, why, who we share it with and
        how you can remove it.
      </p>

      <h2>What we collect</h2>
      <ul>
        <li><strong>Your account:</strong> name, email address and a securely hashed password. If you sign in with Google, your Google account ID, email, name and profile picture.</li>
        <li><strong>Platforms you connect:</strong> when you connect YouTube, your channel name and statistics, your videos and their views, likes, comments, shares and new subscribers, and YouTube Analytics reports such as traffic sources and the countries views come from, always as totals, never individual viewers. When you connect SoundCloud, your profile and your tracks' play, like, repost and comment counts. If you connect TikTok or Instagram once available, your profile and your own posts' views, likes, comments, shares and audience countries as totals.</li>
        <li><strong>Files you upload:</strong> for example distributor reports, which contain song titles, stores, countries, stream counts and earnings.</li>
        <li><strong>Security data:</strong> sign-in sessions and, to stop password guessing, recent failed sign-in attempts with the IP address they came from.</li>
      </ul>
      <p>We do not use advertising or tracking cookies. The only cookie we set keeps you signed in.</p>

      <h2>How we use it</h2>
      <ul>
        <li>To show you your analytics: charts, comparisons between releases, alerts and reports.</li>
        <li>To answer questions in the AI panel. When you ask, we send the relevant totals our servers have calculated (for example your releases' views and dates) to our AI provider to write the answer. We do not send your password, platform tokens or files.</li>
        <li>To keep your account secure and the service working.</li>
      </ul>
      <p>We do not sell your data, use it for advertising, or share it with anyone to market to you.</p>

      <h2>Google and YouTube data</h2>
      <p>
        XobaMetrics uses YouTube API Services. By connecting YouTube you also agree to the{" "}
        <a className="text-primary underline" href="https://www.youtube.com/t/terms" target="_blank" rel="noreferrer">YouTube Terms of Service</a>,
        and Google's handling of your data is described in the{" "}
        <a className="text-primary underline" href="https://policies.google.com/privacy" target="_blank" rel="noreferrer">Google Privacy Policy</a>.
        XobaMetrics' use and transfer of information received from Google APIs adheres to the{" "}
        <a className="text-primary underline" href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noreferrer">Google API Services User Data Policy</a>,
        including the Limited Use requirements. We ask only for read-only access. You can remove XobaMetrics' access at any time from your{" "}
        <a className="text-primary underline" href="https://myaccount.google.com/permissions" target="_blank" rel="noreferrer">Google security settings</a>{" "}
        or with Disconnect on the Connections page, which also deletes our copy of the access tokens.
      </p>

      <h2>Who we share it with</h2>
      <p>Only the companies that run parts of the service for us, and only to run it:</p>
      <ul>
        <li>Railway (servers and database), Vercel (website hosting) and Cloudflare (domain name service).</li>
        <li>Anthropic (the AI that writes answers in the AI panel), as described above.</li>
        <li>Google, YouTube, SoundCloud, TikTok and Meta, when you choose to sign in with or connect them.</li>
      </ul>
      <p>A report you share by public link can be seen by anyone who has the link, until you delete the report.</p>

      <h2>Where it is stored and how it is protected</h2>
      <p>
        Data is stored in the United States. Connections use HTTPS; platform access tokens are encrypted in our
        database; passwords are stored only as salted hashes.
      </p>

      <h2>How long we keep it</h2>
      <p>
        We keep your data while you have an account. Disconnecting a platform deletes its access tokens right away.
        Deleting your account deletes your account and everything in it from our database at once; copies in our
        hosting provider's backups expire on their own schedule.
      </p>

      <h2>Your choices</h2>
      <ul>
        <li>Disconnect any platform on the Connections page.</li>
        <li>Delete your account and all its data from the account menu (your picture in the top right) → Delete account. See <Link className="text-primary underline" to="/data-deletion">Data deletion</Link>.</li>
        <li>Ask us for a copy of your data or to correct it by writing to <Contact />.</li>
      </ul>

      <h2>Children</h2>
      <p>XobaMetrics is not meant for children under 13 (under 16 in the EU and UK), and we do not knowingly collect their data.</p>

      <h2>Changes and contact</h2>
      <p>If we change this policy we will update the date at the top. Questions: <Contact />.</p>
    </Page>
  );
}

export function Terms() {
  return (
    <Page title="Terms of Service">
      <p>These terms apply when you use XobaMetrics (xobametrics.com). By creating an account you agree to them.</p>

      <h2>The service</h2>
      <p>
        XobaMetrics brings together analytics from platforms you connect and files you upload, and helps you compare
        releases. It is in private beta: features can change, and some may be unavailable at times.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>Keep your sign-in details safe; you are responsible for what happens under your account.</li>
        <li>Only connect accounts and upload data you are allowed to use.</li>
      </ul>

      <h2>Your data</h2>
      <p>
        Your data stays yours. You let us store and process it only to provide the service to you, as described in our{" "}
        <Link className="text-primary underline" to="/privacy">Privacy Policy</Link>. You can delete it at any time.
      </p>

      <h2>Other platforms</h2>
      <p>
        Connections use each platform's official access. When you use the YouTube features you agree to the{" "}
        <a className="text-primary underline" href="https://www.youtube.com/t/terms" target="_blank" rel="noreferrer">YouTube Terms of Service</a>;
        the same applies to the terms of any other platform you connect. We are not responsible for those platforms,
        their data or their availability.
      </p>

      <h2>Acceptable use</h2>
      <p>Don't misuse the service: no attempts to access other people's data, to break or overload it, or to use it against the law or platform rules.</p>

      <h2>AI answers and estimates</h2>
      <p>AI answers and figures such as estimated earnings are aids, not advice. They can be wrong; check anything important against the source.</p>

      <h2>No warranty and limits</h2>
      <p>
        The service is provided as it is, without warranties. To the extent the law allows, we are not liable for
        indirect losses, lost profits or lost data, and our total liability is limited to what you paid us in the
        previous 12 months.
      </p>

      <h2>Ending</h2>
      <p>You can stop at any time by deleting your account. We may suspend accounts that break these terms.</p>

      <h2>Changes and contact</h2>
      <p>If we change these terms we will update the date at the top. Questions: <Contact />.</p>
    </Page>
  );
}

export function DataDeletion() {
  return (
    <Page title="Deleting your data">
      <h2>Delete your account and everything in it</h2>
      <ol className="ml-5 list-decimal space-y-1.5">
        <li>Sign in at <Link className="text-primary underline" to="/login">xobametrics.com</Link>.</li>
        <li>Click your picture or initials in the top right, then <strong>Delete account</strong>.</li>
        <li>Type DELETE (and your password, if you use one) and confirm.</li>
      </ol>
      <p>
        This immediately deletes your account, profiles, releases, analytics, reports, uploaded files and platform
        connections from our database, and asks Google to revoke our YouTube access.
      </p>

      <h2>Remove one platform only</h2>
      <p>On the Connections page, click Disconnect next to the platform. Its access tokens are deleted straight away.</p>

      <h2>Remove our access from the platform's side</h2>
      <ul>
        <li>Google / YouTube: <a className="text-primary underline" href="https://myaccount.google.com/permissions" target="_blank" rel="noreferrer">myaccount.google.com/permissions</a> → XobaMetrics → Remove access.</li>
        <li>TikTok: Settings and privacy → Security → Apps and services permissions → XobaMetrics → Remove.</li>
        <li>Instagram or Facebook: Settings → Apps and websites → XobaMetrics → Remove.</li>
      </ul>
      <p>If you remove access this way, our copy of your data stays until you delete it in XobaMetrics or ask us to.</p>

      <h2>Can't sign in?</h2>
      <p>Write to <Contact /> from the email address on your account and we will delete it for you within 30 days.</p>
    </Page>
  );
}
