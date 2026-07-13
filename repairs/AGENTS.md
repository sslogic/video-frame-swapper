# Purpose

- Store one-shot scripts that reproduce lasting program repairs.

# Ownership

- Each script owns one narrowly named repair and must fail safely when its expected source code is not present.

# Local Contracts

- Scripts must create a complete backup of every existing target file before changing it.
- Scripts must replace exact known code, refuse ambiguous matches, and verify the repaired text after writing.

# Work Guidance

- Prefer PowerShell for repairs in this Windows workspace.

# Verification

- Run the repair script and then run the target program's relevant verification.

# Child DOX Index
