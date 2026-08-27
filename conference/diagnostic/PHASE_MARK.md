# Frozen diagnostic PHASE_MARK instrumentation

The conference experiments use llama.cpp submodule commit
`571d0d540df04f25298d0e159e520d9fc62ed121` with
`llama_cpp_phase_mark.patch` applied.

The patch reconstructs and version-controls the diagnostic instrumentation
used by C01/C02. The historical build was made from a temporarily modified
`src/llama-context.cpp`; the source modification itself had not been committed.
The compiled historical object proves the following behavior:

- `CLOCK_MONOTONIC` is read with `clock_gettime`.
- The marker is emitted on the first `llama_context::graph_compute` call and
  whenever its `batched` argument changes.
- The exact record is
  `PHASE_MARK batched=%d t_mono_ns=%lld` and stderr is flushed immediately.
- The C01/C02/C03 boundary remains the first measured-request marker with
  `batched=0`: the first internally marked unbatched decode computation.

This is diagnostic instrumentation, not application phase input for the C03
external detector. The marker is used only to label signal samples offline.

The historical diagnostic CMake cache recorded:

```text
CMAKE_BUILD_TYPE=Release
BUILD_SHARED_LIBS=ON
GGML_NATIVE=ON
GGML_OPENMP=ON
GGML_OPENMP_ENABLED=ON
LLAMA_BUILD_SERVER=ON
```

The AMD build helper freezes these options explicitly. `GGML_NATIVE=ON` is
retained because it was the historical build policy; the AMD collaborator
must build on the AMD machine rather than copy the Intel-built binary.
