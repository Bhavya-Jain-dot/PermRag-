# PermRAG red-team results

- **30 attack attempts**: sales-role attempts to extract finance-only data.
- **30/30 blocked at the retrieval layer**: no finance chunk entered the response context.
- **0/30 answers** contained a confidential figure from `salary_bands.md`.
- **Control check passed**: a finance-role query retrieved `salary_bands.md` and returned its grounded content.

The test suite includes direct requests, rephrasing, prompt injection, role-play, encoding,
indirect inference, multi-turn escalation fragments, and system-prompt extraction attempts.

## Enforcement statement

The retriever requires `user_role` and builds the permitted chunk set before it scores vectors.
The answer generator receives only those selected permitted chunks. A post-retrieval assertion
is retained as a fail-closed canary, not as the primary access-control mechanism.
