This folder holds recordings of real model output for synthetic notes only, so the demo and the
end-to-end tests can replay genuine drafts at no cost. Each file is written by `make record-replays`
(`save_recording`) and named by the hash of the request and the model the request asked for; never
edit one by hand, record it again instead.
