# Dashboard

A web app that keeps the runs of the gate action and shows them per repository: the verdict of each pull request, the
cases that changed between the two versions, and each run's answer, checks and steps on both sides. It runs on Vercel at
https://llm-release-gate.vercel.app.

## How runs get here

A GitHub App, installed on the repositories that run the gate action, gets a `workflow_run` webhook when a workflow run
finishes (`app/api/github/webhook`). The app answers at once, then downloads the run's `release-gate*` artifacts and
stores each as one row in Postgres (`db/schema.sql`): the run's metadata, the verdict, the comment and the records the
gate compared. Installing the App on a repository reads the gate runs among its 1,000 newest artifacts (GitHub deletes
artifacts after 90 days by default). **Read runs from GitHub** on a project's page does the same by hand, also for a run
whose webhook failed: the app logs such a failure and moves on. The project's workflow needs no change and no secret.
Rows stay in the database when the App is uninstalled; nobody sees them until it is installed again.

Signing in goes through the same App (`app/api/auth`). A user sees the repositories where the App is installed and they
have access on GitHub, checked against GitHub on every page. The App's user token lives eight hours; after that the
next page goes through GitHub again, which skips the prompt for a user who already authorized the App.

The records hold what the application answered, its tool calls with their results and the state it ended in. They leave
the CI for the database: install the App only on repositories whose runs may leave it.

## The App

| Setting | Value |
|---|---|
| Permissions | Actions: read (runs and artifacts), Metadata: read |
| Events | Workflow run (installation events come without subscribing) |
| Callback URL | `<site>/api/auth/callback` |
| Webhook URL | `<site>/api/github/webhook`, with a secret |
| Setup URL | `<site>` |

## Settings

| Variable | What |
|---|---|
| `DATABASE_URL` | Postgres |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY` | to act as the App: read artifacts, link to its installation page |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | the App's OAuth credentials, for signing in |
| `GITHUB_WEBHOOK_SECRET` | to check that a webhook comes from GitHub |
| `SESSION_SECRET` | a long random string; encrypts the session cookie |

## Develop

```sh
npm ci
vercel env pull .env.local       # or write the variables above into it
npm run db:migrate               # creates the tables, once
npm run dev                      # http://localhost:3000
npm run lint && npm run typecheck && npm test
```

The tests run without a network or a database: artifact parsing, the comparison of cases, the session cookie, the
webhook signature and the App's token.
