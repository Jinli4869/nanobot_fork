# Android Deep Link Probing Method

This reference captures the operating model behind the skill. Load it only when you need deeper interpretation or want to expand the helper.

## Core idea

Use two layers together:

1. Black-box probing with `adb shell am start -W -a android.intent.action.VIEW -d <URI> <PACKAGE>`
2. System-layer inspection with `dumpsys package`

The first tells you what the app does. The second helps explain why.

## Fast path

Use this when the goal is to reach an app state quickly:

1. Test a compact set of high-probability custom-scheme candidates.
2. Test matching `https` links if a host is known.
3. Stop as soon as one URI opens the right page or reliably opens the app shell.
4. Return only:
   - viable URIs
   - partial matches
   - next candidates worth trying

## Investigate path

Use this when fast mode cannot reach the desired state:

1. Expand path variants:
   - `search`
   - `search/`
   - `search/result`
   - `note/123`
   - `profile/<id>`
2. Expand parameter names:
   - `q`
   - `query`
   - `keyword`
   - `id`
   - `url`
3. Check:
   - `adb shell dumpsys package <PACKAGE>`
   - `adb shell dumpsys package domain-preferred-apps`
4. Look for:
   - `VIEW`
   - `BROWSABLE`
   - `scheme`
   - `host`
   - `path`
   - suspected route fragments

## Reading outcomes

### `unable to resolve Intent`

Usually means:

- the route is not registered
- or the `scheme`, `host`, `path`, or query layout is wrong

### App opens but lands on home/fallback

Usually means:

- the app has a matching entry activity
- but the business route or parameters are not recognized

### `http/https` keeps opening the browser

Usually means:

- it is a standard web link rather than a validated app link
- or the device has not approved that domain for the package

## Main-agent hygiene

Do not send raw dumpsys output unless the user asks for it. Distill it into a few statements:

- which URI families seem real
- whether the package appears to register browsable routes
- whether domain preference or app-link verification looks like the blocker
