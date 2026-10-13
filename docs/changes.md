# Client changes (2026-10-12): model switch rollback

Use this to update the iOS app (SwiftUI). Backend behavior change only, no new event types.

## Backend
- `set_model` over the WebSocket still persists `overrides.model` first and emits a `session` event, so the
  picker can update immediately (optimistic, no pending state needed).
- If the CLI rejects the model (any exception, e.g. `Model 'x' not found`), the CLI keeps its old model.
  The server now restores the previous `overrides.model`, emits another `session` event with it, an
  `error` notice item, and an `error` reply carrying the `req_id`.

## What the client should do
- Keep showing the picked model right away.
- Always derive the displayed model from the latest `session.overrides.model`, so the second `session`
  event flips the picker back on its own.
- On the `error` reply for that `req_id`, show the message (toast). Don't show a success toast until the
  reply window passes without an error.
