// The licence and credit texts that must travel with the 3D view. They are bundled into the app (this file is part of the
// lazily loaded 3D view chunk) and shown in the panel, so every installed copy carries them without any installer change.
// The two vendored files are imported as plain text; this is the only file besides the facade and the adapter that may
// name the vendor tree, and only for these two assets (see readOnly.guard.test.ts).
import slicerxNotice from "@/vendor/slicerx/NOTICE?raw";
import apacheLicense from "@/vendor/slicerx/LICENSE-APACHE?raw";

export const SLICERX_CREDIT = "Made possible by SlicerX: https://slicerx.app/support";

export const THREE_LICENSE = `The MIT License

Copyright © 2010-2026 three.js authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.`;

export const CREDIT_SECTIONS: { title: string; text: string }[] = [
  { title: "SlicerX notice (Apache-2.0)", text: slicerxNotice },
  { title: "Apache License 2.0 (SlicerX viewport)", text: apacheLicense },
  { title: "three.js (MIT)", text: THREE_LICENSE },
];
