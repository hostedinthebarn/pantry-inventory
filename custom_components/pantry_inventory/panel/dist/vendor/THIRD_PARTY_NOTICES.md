# Third-party code in this folder

These files are copied in unmodified so the panel works with no build step and no internet connection.

| File | Project | Version | Licence |
|---|---|---|---|
| `lit-core.min.js` | [Lit](https://github.com/lit/lit) (lit-html 3.3.3, lit-element 4.2.2, @lit/reactive-element 2.1.2) | 3.3.x | BSD-3-Clause, Copyright The Lit Project Contributors |
| `reader/index.js`, `share.js` | [zxing-wasm](https://github.com/Sec-ant/zxing-wasm) | 3.1.3 | MIT, Copyright (c) 2023 Ze-Zheng Wu |
| `reader/zxing_reader.wasm` | [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp), compiled by zxing-wasm | as bundled in zxing-wasm 3.1.3 | Apache-2.0 |

`ha-panel-base.js` is part of this project and is covered by the repository's MIT licence.

The full licence texts are at the links above:

- BSD-3-Clause: https://github.com/lit/lit/blob/main/LICENSE
- MIT (zxing-wasm): https://github.com/Sec-ant/zxing-wasm/blob/main/LICENSE
- Apache-2.0 (zxing-cpp): https://github.com/zxing-cpp/zxing-cpp/blob/master/LICENSE
