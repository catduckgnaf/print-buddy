import { fuzzyScore } from "@/lib/fuzzy";

export type CatalogItem = {
  id: string;
  title: string;
  file: string;
  tags: string[];
};

/** Sample models. Search, Chat, and the CLI all read this list. */
export const CATALOG: CatalogItem[] = [
  { id: "benchy", title: "3D Benchy", file: "benchy.stl", tags: ["boat", "calibration"] },
  { id: "cube", title: "Calibration cube", file: "calibration-cube.stl", tags: ["cube", "calibration"] },
  { id: "clip", title: "Cable clip", file: "cable-clip.stl", tags: ["cable", "clip", "desk"] },
  { id: "spool", title: "Spool holder", file: "spool-holder.3mf", tags: ["spool", "holder"] },
  { id: "tower", title: "Temperature tower", file: "temp-tower.stl", tags: ["temperature", "tower"] },
  { id: "stand", title: "Phone stand", file: "phone-stand.stl", tags: ["phone", "stand"] },
  { id: "bin", title: "Gridfinity bin", file: "gridfinity-bin.3mf", tags: ["gridfinity", "bin", "storage"] },
  { id: "hinge", title: "Print-in-place hinge", file: "hinge.stl", tags: ["hinge"] },
  { id: "knob", title: "Drawer knob", file: "drawer-knob.stl", tags: ["drawer", "knob"] },
  { id: "tolerance", title: "Tolerance test", file: "tolerance-test.stl", tags: ["tolerance", "test"] },
];

export type CatalogHit = { item: CatalogItem; score: number };

/** Empty query returns the full catalog so a shorter search expands the list. */
export function searchCatalog(query: string): CatalogHit[] {
  const text = query.trim();
  if (!text) return CATALOG.map((item) => ({ item, score: 1 }));
  return CATALOG.map((item) => ({
    item,
    score: Math.max(
      fuzzyScore(text, item.title),
      fuzzyScore(text, item.file),
      fuzzyScore(text, item.id),
      ...item.tags.map((tag) => Math.max(0, fuzzyScore(text, tag) - 40)),
    ),
  }))
    .filter((hit) => hit.score >= 280)
    .sort((a, b) => b.score - a.score || a.item.title.localeCompare(b.item.title));
}

export function catalogByFile(file: string): CatalogItem | undefined {
  const key = file.trim().toLowerCase();
  return CATALOG.find((item) => item.file.toLowerCase() === key);
}
