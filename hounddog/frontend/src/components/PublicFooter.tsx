import { useBranding } from "../useBranding";

export default function PublicFooter() {
  const brand = useBranding();

  return (
    <footer className="border-t mt-12 py-6 px-4 text-center">
      <div className="max-w-4xl mx-auto flex flex-col items-center gap-3">
        <a
          href="/regulations"
          target="_blank"
          rel="noopener noreferrer"
          className="font-semibold text-sm underline underline-offset-2 hover:opacity-80"
          style={{ color: brand.primaryColor }}
        >
          📋 Parking Rules &amp; Regulations
        </a>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>&copy; {new Date().getFullYear()} {brand.schoolName || "Moravian University"}</span>
          <span>·</span>
          <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-gray-600 underline underline-offset-2">
            Privacy Policy
          </a>
        </div>
      </div>
    </footer>
  );
}
