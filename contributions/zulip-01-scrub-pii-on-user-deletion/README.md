# zulip/zulip #39347 — Scrub additional PII tables on user deletion

**Upstream repo:** https://github.com/zulip/zulip
**Issue:** https://github.com/zulip/zulip/issues/39347
**Area:** backend (Python/Django), security/privacy
**Difficulty:** moderate–hard

## The bug

`do_delete_user_core` (in `zerver/actions/users.py`) "deletes" a user by
overwriting the `UserProfile` row in place with scrubbed defaults, rather
than actually deleting the row. That's deliberate (it keeps message
history and IDs consistent), but it has a side effect: since the row is
never deleted, Django's `on_delete=CASCADE` never fires for other tables
that have a foreign key to it. An explicit `fks_to_delete` list is
supposed to compensate, but it was missing several tables that carry
personally identifying information:

- `CustomProfileFieldValue` — bio, phone number, and other custom profile answers
- `UserStatus` — status text/emoji
- `AlertWord` — a user's custom alert keywords
- `PushDeviceToken` / `Device` — mobile device identifiers
- `EmailChangeStatus` — pending old/new email address pairs
- Uploaded avatar image files were also left behind in storage (local disk or S3), since only the DB pointer to them was reset, not the files themselves.

Net effect: "deleting" a user did not fully scrub their PII, contrary to
what admins/GDPR-type deletion requests would expect.

## The fix

- Added the six models above to the `fks_to_delete` list in
  `do_delete_user_core`, so their rows are explicitly deleted.
- Captured the user's `avatar_version` *before* the overwrite (which resets
  it to the default) and used it to call `delete_avatar_image` for every
  version that existed, removing the actual files from storage — mirroring
  the existing `do_scrub_avatar_images` helper's approach, adapted for the
  fact that the DB fields here are reset via bulk `update()` rather than
  through that helper.
- Added two regression tests in `zerver/tests/test_users.py`:
  - `DeleteUserTest.test_do_delete_user_scrubs_pii` — creates one row in
    each of the six tables for a test user, deletes the user, and asserts
    every row is gone.
  - `DeleteUserAvatarTest.test_do_delete_user_scrubs_avatar_images` (new
    `UploadSerializeMixin` test class, matching the existing pattern used
    for other avatar-file-on-disk tests) — uploads a real avatar image,
    deletes the user, and asserts the three avatar file variants
    (thumbnail/medium/original) no longer exist on disk.

## Verification performed

- `ruff check` and `ruff format --check` on both changed files: clean.
- Manually traced `do_delete_user_core`'s control flow line-by-line against
  each new deletion to confirm field names/relations
  (`CustomProfileFieldValue.user_profile`, `PushDeviceToken.user`,
  `Device.user`, etc.) and that avatar-version capture happens before the
  row is overwritten.
- Confirmed `delete_avatar_image`/`delete_avatar_image_from_storage` are
  safe to call for versions that were never actually uploaded (already an
  established pattern via the existing `do_scrub_avatar_images`), so no new
  scenario relies on files being guaranteed to exist.
- **Not run:** the full Django test suite (`tools/test-backend`) — this
  sandbox has no provisioned Postgres/dev environment for Zulip. A
  maintainer or CI should confirm:
  `tools/test-backend zerver.tests.test_users.DeleteUserTest zerver.tests.test_users.DeleteUserAvatarTest`

## Status

**Not yet submitted upstream.** See the top-level `contributions/README.md`
for why, and what's needed to open the actual PR against `zulip/zulip`.

`fix.patch` in this directory is the exact `git diff` to apply (from the
root of a `zulip/zulip` checkout) with `git apply fix.patch`.
