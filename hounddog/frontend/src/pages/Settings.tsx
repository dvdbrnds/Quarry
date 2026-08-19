import { useSearchParams } from "react-router-dom";
import { Tabs } from "antd";
import ActivityLog from "./ActivityLog";
import Messaging from "./Messaging";
import DataManagement from "./DataManagement";
import BrandingSettings from "./BrandingSettings";
import FeatureSettings from "./FeatureSettings";
import { useCurrentUser } from "../UserContext";
import { isAdminRole } from "../auth";

const ALL_TABS = [
  { key: "messaging", label: "Messaging", children: <Messaging /> },
  { key: "branding", label: "Branding", children: <BrandingSettings /> },
  { key: "features", label: "Features", children: <FeatureSettings /> },
  { key: "activity", label: "Activity Log", children: <ActivityLog /> },
  { key: "data", label: "Data Management", children: <DataManagement /> },
];

const OPERATOR_TAB_KEYS = new Set(["activity"]);

export default function Settings() {
  const user = useCurrentUser();
  const isAdmin = isAdminRole(user?.role);
  const tabs = isAdmin ? ALL_TABS : ALL_TABS.filter((t) => OPERATOR_TAB_KEYS.has(t.key));
  const defaultKey = isAdmin ? "messaging" : "activity";

  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const activeKey = tabs.some(t => t.key === tabParam) ? tabParam! : defaultKey;

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Settings</h2>
      <Tabs
        activeKey={activeKey}
        onChange={(key) => setSearchParams({ tab: key })}
        items={tabs}
      />
    </div>
  );
}
