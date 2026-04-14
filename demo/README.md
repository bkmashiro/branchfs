# BranchFS Demo

## ai_exploration.py

Simulates an AI agent exploring three different approaches to a problem using BranchFS branches.

### What it does

1. Creates a workspace with a problem description
2. Takes a baseline snapshot
3. Forks three branches, one per approach
4. In each branch, the "AI" writes solution code and tests
5. Scores each approach
6. Discards the two losers (changes vanish)
7. Merges the winner into a new snapshot
8. Prints the full history tree

### Running it

```bash
# From the repo root:
python demo/ai_exploration.py

# Or if installed:
cd demo && python ai_exploration.py
```

### Expected output

```
Workspace: /tmp/branchfs_demo_xxxxx

Initialized. Baseline snapshot: a1b2c3d4e5f6
Files: ['problem.txt', 'constraints.txt']

--- Exploring: timsort ---
  Changes: {'solution.py': 'added', 'tests.py': 'added', 'README.md': 'added'}
  Score:   0.95

--- Exploring: bubble-optimized ---
  Changes: {'solution.py': 'added', 'tests.py': 'added'}
  Score:   0.30

--- Exploring: insertion-adaptive ---
  Changes: {'solution.py': 'added', 'tests.py': 'added', 'README.md': 'added'}
  Score:   0.75

Winner: timsort (score=0.95)

Discarding: insertion-adaptive
Discarding: bubble-optimized
Merging: timsort
New snapshot: ...

=== History ===
* [a1b2c3] init  (2 files)
|\
| o [d4e5f6] timsort  +3 -0
|
* [g7h8i9] winner-timsort  (5 files)

=== Final files ===
  README.md
  constraints.txt
  problem.txt
  solution.py
  tests.py

Done!
```

The key takeaway: the agent tried three approaches, and the two failed attempts left **zero trace** in the final workspace. No manual cleanup, no leftover files, no git stash juggling.
