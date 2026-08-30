/** flash 闪白转场：与 fade 同一算法，中间色默认白色。 */

import { makeVeiledFade } from "./fade.ts";

export const flash = makeVeiledFade("flash", "#FFFFFF");
