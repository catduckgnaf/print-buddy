/** Shared matcher for Search, Chat, and the CLI. Higher is better. 0 is no match. */
export function fuzzyScore(query: string, text: string): number {
  const needle = normalize(query);
  const hay = normalize(text);
  if (!needle || !hay) return 0;
  if (hay === needle) return 1000;
  if (hay.startsWith(needle)) return 860;
  if (hay.includes(needle)) return 720;

  let matched = 0;
  let gaps = 0;
  let last = -2;
  for (let i = 0; i < hay.length && matched < needle.length; i++) {
    if (hay[i] !== needle[matched]) continue;
    if (last >= 0) gaps += i - last - 1;
    last = i;
    matched += 1;
  }
  if (matched === needle.length) return Math.max(280, 560 - gaps * 12);

  if (Math.abs(hay.length - needle.length) > 2 || needle.length < 3) return 0;
  const distance = editDistance(needle, hay);
  if (distance === 0) return 1000;
  if (distance === 1) return 640;
  if (distance === 2 && needle.length >= 5) return 420;
  return 0;
}

export function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function editDistance(a: string, b: string): number {
  const prev = new Array<number>(b.length + 1);
  const row = new Array<number>(b.length + 1);
  for (let j = 0; j <= b.length; j++) prev[j] = j;
  for (let i = 1; i <= a.length; i++) {
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      row[j] = Math.min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
    }
    for (let j = 0; j <= b.length; j++) prev[j] = row[j];
  }
  return prev[b.length] ?? 99;
}
