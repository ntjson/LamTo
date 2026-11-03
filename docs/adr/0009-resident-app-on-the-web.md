---
status: accepted
---

# Build the Resident app for the web, and serve it from the API's origin

LamTo has no Mac, no Apple Developer account and no budget, so there is no way
to put a native build on a resident's iPhone. The Resident app is therefore
also built for the web, and the web is how an iPhone resident gets it — in
demos and in any pilot, not as a demo-only channel. Android residents can use
the same web build or the APK. It is the same product on a third platform, not
a separate resident website: a second product would split the vocabulary the
glossary already rules out ("resident web page", "resident web app").

## Considered options

A native iOS build through TestFlight or the App Store was rejected because it
needs both a Mac and a paid Apple account. Serving the web build from its own
origin was rejected because Django has no CORS and adding it would open the
resident API to cross-origin callers for no benefit; one origin keeps the API
closed and needs no new configuration.

## Consequences

The web build lives under `/app/`, because `/` belongs to the Management
workspace. It takes its API address from the page it was loaded from, so a new
hostname needs no rebuild. The resident API authenticates by token only, so a
Management session cookie on the same origin is ignored rather than mistaken
for a resident.

Three capabilities are absent on the web: bill scan, gate face enrolment and
push notifications. The gate reader is a separate kiosk build and is never
built for the web.

Report photos are read and uploaded as bytes, and their content type comes
from their leading bytes, never from a filename — the same rule ADR 0006 set
for documents. A web report draft keeps its text across a page reload but not
its photos.

ADR 0004 and ADR 0006 hold unchanged: the Evidence explorer opens in a new
browser tab, so its real address stays visible, and documents open in the
in-app viewer.

**Known gaps before a real pilot.** The login token is kept in browser storage
with its encryption key beside it, so any script running on the origin can read
it, and Safari deletes that storage after seven days without a visit. Vietnamese
Telex input in iOS Safari is unverified; residents can type without accents or
dictate, and that was accepted as not blocking.
