# TASK-C03 AMD cross-vendor preflight

**PRECHECK STATUS: FAIL**

- CPU model: AMD Ryzen AI 9 HX 370 w/ Radeon 890M
- Vendor: AuthenticAMD
- Physical/logical: 12/24
- Allowed affinity: 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23
- Git commit: ce8dfaa6ac3b4db1afb6f15a9c33b3b18aab0e1d
- Error: llama.cpp source differs from the expected diagnostic patch state: ['M src/llama-context.cpp']

## Physical-core evidence

| package | core_id | representative | siblings | highest_perf | nominal_perf | max_freq_khz | capacity | core_type | conflicts |
|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| 0 | 0 | 0 | 0,12 | 196 | 76 | 5157895 | 1024 | None |  |
| 0 | 1 | 1 | 1,13 | 208 | 76 | 5157895 | 1024 | None |  |
| 0 | 2 | 2 | 2,14 | 202 | 76 | 5157895 | 1024 | None |  |
| 0 | 3 | 3 | 3,15 | 208 | 76 | 5157895 | 1024 | None |  |
| 0 | 8 | 4 | 4,16 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 9 | 5 | 5,17 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 10 | 6 | 6,18 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 11 | 7 | 7,19 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 12 | 8 | 8,20 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 13 | 9 | 9,21 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 14 | 10 | 10,22 | 125 | 76 | 3289474 | 1024 | None |  |
| 0 | 15 | 11 | 11,23 | 125 | 76 | 3289474 | 1024 | None |  |
