# GPU spike

Run through `fr run` with a task GPU UUID in the campaign's `[gpu]` section.
The verifier checks the CUDA driver API directly. Set `EXPECT_GPU` in
`[verifier.env]` to also check the device name.
