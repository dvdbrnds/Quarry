import { Input, Select } from "antd";

export interface MailingAddress {
  street: string;
  unit: string;
  city: string;
  state: string;
  zip: string;
}

export type AddressErrors = Partial<Record<keyof MailingAddress, string>>;

export const EMPTY_ADDRESS: MailingAddress = { street: "", unit: "", city: "", state: "", zip: "" };

const US_STATES = [
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
  "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
  "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "VI", "GU", "AS", "MP", "AA", "AE", "AP",
];

const STREET_RE = /^\d+[A-Za-z]?(-\d+[A-Za-z]?)?\s+([NSEW]\.?\s+)?[A-Za-z0-9][A-Za-z0-9.'\- ]*[A-Za-z][A-Za-z0-9.'\- ]*$/;
const PO_BOX_RE = /^(P\.?\s*O\.?\s*Box|Post\s+Office\s+Box)\s+\d+$/i;
const CITY_RE = /^[A-Za-z][A-Za-z.'\- ]*[A-Za-z]$/;
const ZIP_RE = /^\d{5}(-\d{4})?$/;

export function validateAddress(a: MailingAddress): AddressErrors {
  const errors: AddressErrors = {};
  const street = a.street.trim();
  if (!street) errors.street = "Required";
  else if (!STREET_RE.test(street) && !PO_BOX_RE.test(street)) errors.street = "Must be a house number and street name (e.g. 119 W Greenwich St) or PO Box 123";
  if (a.unit.trim().length > 20) errors.unit = "Too long";
  const city = a.city.trim();
  if (!city) errors.city = "Required";
  else if (!CITY_RE.test(city)) errors.city = "Letters only (e.g. Bethlehem)";
  if (!US_STATES.includes(a.state)) errors.state = "Required";
  const zip = a.zip.trim();
  if (!zip) errors.zip = "Required";
  else if (!ZIP_RE.test(zip)) errors.zip = "5 digits (or ZIP+4)";
  return errors;
}

export function isValidAddress(a: MailingAddress): boolean {
  return Object.keys(validateAddress(a)).length === 0;
}

/** Stored as "123 Main St Apt 2, Bethlehem, PA 18018" (street line, then city line after the first comma). */
export function formatAddress(a: MailingAddress): string {
  const street = [a.street.trim(), a.unit.trim()].filter(Boolean).join(" ");
  return `${street}, ${a.city.trim()}, ${a.state} ${a.zip.trim()}`;
}

/** Best-effort split of a stored one-line address back into fields; anything unparseable lands in street. */
export function parseAddress(text: string | null | undefined): MailingAddress {
  const t = (text || "").replace(/\s*\n\s*/g, ", ").trim();
  if (!t) return { ...EMPTY_ADDRESS };
  const m = t.match(/^(.+?),\s*([^,]+?),?\s+([A-Za-z]{2})\.?\s+(\d{5}(?:-\d{4})?)$/);
  if (!m) return { ...EMPTY_ADDRESS, street: t };
  const state = m[3].toUpperCase();
  return { street: m[1].trim(), unit: "", city: m[2].trim(), state: US_STATES.includes(state) ? state : "", zip: m[4] };
}

export function AddressFields({ value, onChange, errors, size }: {
  value: MailingAddress;
  onChange: (next: MailingAddress) => void;
  errors?: AddressErrors;
  size?: "small" | "middle";
}) {
  const set = (k: keyof MailingAddress) => (v: string) => onChange({ ...value, [k]: v });
  const field = (label: string, k: keyof MailingAddress, node: React.ReactNode, className = "") => (
    <div className={className}>
      <label className="text-xs text-gray-500 block mb-1">{label}</label>
      {node}
      {errors?.[k] && <div className="text-xs text-red-600 mt-0.5">{errors[k]}</div>}
    </div>
  );
  return (
    <div className="grid grid-cols-6 gap-2">
      {field("Street number and name", "street",
        <Input size={size} value={value.street} status={errors?.street ? "error" : undefined}
          onChange={(e) => set("street")(e.target.value)} placeholder="119 W Greenwich St" />, "col-span-4")}
      {field("Apt / Unit", "unit",
        <Input size={size} value={value.unit} status={errors?.unit ? "error" : undefined}
          onChange={(e) => set("unit")(e.target.value)} placeholder="Apt 2B" />, "col-span-2")}
      {field("City / Town", "city",
        <Input size={size} value={value.city} status={errors?.city ? "error" : undefined}
          onChange={(e) => set("city")(e.target.value)} placeholder="Bethlehem" />, "col-span-3")}
      {field("State", "state",
        <Select size={size} value={value.state || undefined} status={errors?.state ? "error" : undefined} showSearch
          onChange={set("state")} placeholder="PA" options={US_STATES.map((s) => ({ value: s, label: s }))} className="w-full" />, "col-span-1")}
      {field("ZIP", "zip",
        <Input size={size} value={value.zip} status={errors?.zip ? "error" : undefined} maxLength={10}
          onChange={(e) => set("zip")(e.target.value.replace(/[^\d-]/g, ""))} placeholder="18018" />, "col-span-2")}
    </div>
  );
}
