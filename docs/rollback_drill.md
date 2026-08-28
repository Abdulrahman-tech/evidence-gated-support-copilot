# Rollback drill record

## 2026-08-28 Render free-tier drill

Scope: verify that the public demo can move from a newer release to a known-good
release and then return to the current release without violating the public
health, readiness, metrics, security-header, or release-identity contracts.

- Known-good release: `c36d4716dbcf601909bb93fa82c4d27af727ebb6`
- Candidate release: `add8b7c5663337886cecbc2458c7fdbbdc782bd5`
- Rollback mechanism: Render successful-deploy rollback
- Verification: `scripts/check_live_service.py --expected-release FULL_COMMIT_SHA`
- Status: passed

No confidential traffic or paid provider calls are part of this drill.

### Observed result

1. Candidate `add8b7c` deployed and passed the complete public contract with its
   exact release identifier.
2. Render rollback switched the service to known-good `c36d471` in 20.3 seconds.
3. The public contract passed and reported the exact known-good SHA.
4. Candidate `add8b7c` was restored and again passed the complete contract with
   its exact SHA.
5. The rollback-disabled auto-deploy setting was restored from the Blueprint to
   `checksPass`.

The drill tested release switching and restoration, not an SLA. Render's free
tier, cold starts, and six-hour external monitor remain documented limitations.
