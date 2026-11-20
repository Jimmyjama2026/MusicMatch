# Licensed text similarity experiment

This module is intentionally separate from the desktop recommendation path. It does not change UI imports, startup, favorites, ratings, or the existing recommendation algorithm. No network requests occur when querying an index.

Run `python scripts/build_text_index.py --download` manually to acquire only three pinned MulJam v2 metadata files (12,880,118 bytes). No audio, LRCLIB, external language models, or paid services are used. Source artifacts are under the already ignored `data/sources/muljam_text/`. The downloader maintains a cumulative 15,000,000-byte response-payload cap across reruns; failures consume budget. There are no automatic retries. HTTP/TLS headers are outside payload accounting. Read documentation/license evidence separately adds small research transfers.

Whole-response budget reservations are persisted before requests and actual response-byte counts after each chunk. Reservations remain consumed after failed requests or process termination; this deliberately errs toward stopping early. Cached sources are checked against retained SHA-256 hashes and pinned expected sizes before use. Index builds use temporary sibling directories and publish by rename only after all files are written. The experiment root is checked against its 50 MB allowance before and after building; this is separate from the larger project allowance.

An exclusive `.build.lock` prevents concurrent processes from resetting the same transfer ledger or publishing the same index. A forcibly killed build may leave this lock; remove it only after confirming the recorded process is no longer building. The 50 MB disk check detects over-budget files after writing; it is not a streaming filesystem quota. Multiple different corpus indexes accumulate and should be reviewed before further builds. The pinned, measured corpus and its single index occupy 21.31 MB.

## Attribution and terms

Source: Le Zhuo, Ruibin Yuan, Jiahao Pan, Yinghao Ma, Yizhi Li, Ge Zhang, Si Liu, Roger Dannenberg, Jie Fu, Chenghua Lin, and collaborators, *LyricWhiz: Robust Multilingual Zero-shot Lyrics Transcription by Whispering to ChatGPT* (2023), https://arxiv.org/abs/2306.17103 . Repository: https://github.com/zhuole1025/LyricWhiz at commit `0b66527ed2f7ade13944b43364de403f8d99e638`.

The paper identifies the MulJam dataset license as **CC BY-NC-SA**, without specifying a numeric version. Do not invent a version or confuse the paper's own publication license with the dataset license. Preserve this attribution, keep use noncommercial, identify modifications, and preserve applicable ShareAlike terms if adapted data is shared. Source labels/transcriptions may contain mistakes. The repository describes v2 as amended splits and annotations of the MulJam corpus; no separate numeric license version is stated. Distribution licensing is not independently verified for every underlying recording.

Also cite Ruibin Yuan, Yinghao Ma, Yizhi Li, Ge Zhang, Xingran Chen, Hanzhi Yin, Le Zhuo, Yiqi Liu, Jiawen Huang, Zeyue Tian, and collaborators, *MARBLE: Music Audio Representation Benchmark for Universal Evaluation* (2023), https://arxiv.org/abs/2306.10548 . The repository's README additionally credits the human annotators; see the pinned README for the complete acknowledgement: https://github.com/zhuole1025/LyricWhiz/blob/0b66527ed2f7ade13944b43364de403f8d99e638/README.md .

## Representations and retrieval

Segments are assembled into song documents by Jamendo ID. A separate word unigram/bigram TF-IDF model is fitted per supplied language label. Each model has at most 20,000 features. Persist normalized sparse float32 song vectors (NPZ), vocabulary and IDF (JSON), source hashes, model version and corpus hash. No pickle/joblib objects are loaded. The persistent JSON vocabulary contains words/ngrams; representations are **not anonymization or permission circumvention**. Raw licensed source text is retained in the research artifact directory with attribution.

An offline build calculates each song's representation once. At query time a sparse matrix–vector product calculates that song's cosine overlap against its language group, omits the query itself, and returns positive scores. It does not precompute an N-by-N pairwise table. A changed corpus or model version requires a rebuild; because IDF depends on the collection, adding a song requires rebuilding rather than silently mixing incompatible vectors. No cross-language scoring, theme certainty, or individual embedding-dimension interpretation is claimed.

`experiment_report.json` records actual language/song counts, transfer bytes, retained files and sample neighboring IDs without publishing lyric excerpts. These are operational sanity checks, not an accuracy evaluation. A later judged evaluation should compare lexical, existing audio and listening signals using held-out user feedback. No favorite-artist overlap is claimed and no lyric signal enters personal ranking yet.

## First measured run

The pinned v2 splits contain **5,797 unique song IDs**, not the original corpus's reported 6,031: English 3,605; French 1,015; Spanish 616; Italian 305; German 130; Russian 126. Source payloads total **12,880,118 bytes**; retained source/index/report files total approximately **21.31 MB**. The saved experiment report records sixty warm queries across languages averaging approximately **3.14 ms**, with a slowest measured query of **14.93 ms** on this machine. These timings exclude Python startup, loading, and fitting and do not establish end-to-end GUI performance. No code in the GUI imports this experimental module.
