# Rollback drill record

## 2026-08-28 Render free-tier drill

Scope: verify that the public demo can move from a newer release to a known-good
release and then return to the current release without violating the public
health, readiness, metrics, security-header, or release-identity contracts.

- Known-good release: `c36d4716dbcf601909bb93fa82c4d27af727ebb6`
- Candidate release: this documentation-only commit
- Rollback mechanism: Render successful-deploy rollback
- Verification: `scripts/check_live_service.py --expected-release FULL_COMMIT_SHA`
- Status: pending

No confidential traffic or paid provider calls are part of this drill.
