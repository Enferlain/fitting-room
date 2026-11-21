#!/bin/bash
# Pass iff CUDA (not nvidia-smi, which ignores CUDA_VISIBLE_DEVICES) sees exactly one device,
# and, when EXPECT_GPU is set, that device's name contains it.
mkdir -p /logs/verifier
(cc -Wall -Wextra /tests/cudacount.c -o /tmp/cudacount -ldl && /tmp/cudacount) \
    > /logs/verifier/gpus.txt 2>&1
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-<unset>}" >> /logs/verifier/gpus.txt
cat /logs/verifier/gpus.txt
n=$(grep -c '^[0-9] ' /logs/verifier/gpus.txt)
ok=0
if [ "$n" = "1" ]; then
  if [ -z "${EXPECT_GPU:-}" ] || grep -q "$EXPECT_GPU" /logs/verifier/gpus.txt; then ok=1; fi
fi
echo $ok > /logs/verifier/reward.txt
