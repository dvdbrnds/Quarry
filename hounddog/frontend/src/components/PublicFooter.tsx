import { useBranding } from "../useBranding";

export default function PublicFooter() {
  const brand = useBranding();

  return (
    <footer className="border-t mt-12 py-6 px-4 text-center text-xs text-gray-400">
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-center gap-2 sm:gap-4">
        <span>&copy; {new Date().getFullYear()} {brand.schoolName || "Moravian University"}</span>
        <span className="hidden sm:inline">·</span>
        <a href="/regulations" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-gray-600 underline underline-offset-2">
          Parking Regulations
        </a>
        <span className="hidden sm:inline">·</span>
        <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-gray-600 underline underline-offset-2">
          Privacy Policy
        </a>
      </div>
    </footer>
  );
}
