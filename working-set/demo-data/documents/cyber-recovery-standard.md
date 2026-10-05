# Contoso Health Cyber Recovery Standard

## Recovery gates
1. Isolate affected production networks and disable compromised identities before restore activity.
2. Tier-0 workloads require an immutable recovery point no older than their approved RPO.
3. Restore identity and DNS dependencies before dependent applications.
4. Validate candidate recovery points in the clean room with malware scanning and application-owner checks.
5. Security and the application owner must approve production cutover.

## Service objectives
- Tier 0: RPO 15 minutes, RTO 2 hours.
- Tier 1: RPO 4 hours, RTO 8 hours.

Do not treat a successful backup job as proof that a recovery point is clean or recoverable.
