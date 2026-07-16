import { useBranding } from "../useBranding";

export default function PublicPageNav({ subtitle }: { subtitle: string }) {
  const brand = useBranding();
  return (
    <nav
      style={{ background: brand.primaryColor }}
      className="px-6 py-4 shadow-md"
    >
      <div className="max-w-4xl mx-auto flex items-center gap-3">
        {brand.logoUrl && (
          <img
            src={brand.logoUrl}
            alt={brand.brandName}
            className="h-8 w-auto"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        <h1
          style={{ color: brand.accentColor }}
          className="text-lg font-bold tracking-wide"
        >
          {brand.brandName}
        </h1>
        <span className="text-sm text-white/60 ml-1">{subtitle}</span>
      </div>
    </nav>
  );
}
