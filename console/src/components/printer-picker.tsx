import { useMemo } from "react";
import { BRANDS, brandIdFor, modelsFor } from "@/lib/printers";

const selectClass = "w-full rounded-card border border-line bg-bg px-3 py-2 text-ink";

export function PrinterPicker({
  model,
  onModel,
}: {
  model: string;
  onModel: (model: string) => void;
}) {
  const brandId = brandIdFor(model);
  const types = useMemo(() => modelsFor(brandId), [brandId]);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Brand</span>
        <select
          className={selectClass}
          value={brandId}
          onChange={(event) => {
            const next = modelsFor(event.target.value)[0];
            if (next) onModel(next.key);
          }}
        >
          {BRANDS.map((brand) => (
            <option key={brand.id} value={brand.id}>
              {brand.label}
            </option>
          ))}
        </select>
        <span className="text-muted">Vendor, or Other / generic when the machine is not listed.</span>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Type</span>
        <select className={selectClass} value={model} onChange={(event) => onModel(event.target.value)}>
          {types.map((type) => (
            <option key={type.key} value={type.key}>
              {type.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
