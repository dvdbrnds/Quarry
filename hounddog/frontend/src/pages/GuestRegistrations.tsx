import { useCallback, useEffect, useState } from "react";
import { Table, App, Tag, Input, DatePicker, Select } from "antd";
import { authHeaders } from "../auth";
import dayjs from "dayjs";

interface GuestRow {
  id: string;
  host_email: string;
  host_name: string;
  guest_name: string;
  guest_plate: string | null;
  guest_plate_state: string;
  check_in: string;
  check_out: string;
  roommate_consent: boolean;
  notes: string | null;
  status: string;
  created_at: string;
}

export default function GuestRegistrations() {
  const { message } = App.useApp();
  const [rows, setRows] = useState<GuestRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      if (statusFilter) params.set("status", statusFilter);
      if (dateRange?.[0]) params.set("from_date", dateRange[0].format("YYYY-MM-DD"));
      if (dateRange?.[1]) params.set("to_date", dateRange[1].format("YYYY-MM-DD"));

      const res = await fetch(`/api/admin/guests?${params}`, { headers: await authHeaders() });
      if (!res.ok) throw new Error("Failed to load guest registrations");
      setRows(await res.json());
    } catch (e: any) {
      message.error(e.message);
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, dateRange, message]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold m-0">Guest Registrations</h2>
          <p className="text-sm text-gray-500 m-0 mt-1">
            Overnight guest registrations submitted by students
          </p>
        </div>
      </div>

      <div className="flex gap-3 mb-4 flex-wrap">
        <Input.Search
          placeholder="Search host or guest..."
          allowClear
          onSearch={setSearch}
          style={{ width: 260 }}
        />
        <Select
          placeholder="Status"
          allowClear
          onChange={(v) => setStatusFilter(v || undefined)}
          style={{ width: 140 }}
          options={[
            { label: "Active", value: "active" },
            { label: "Cancelled", value: "cancelled" },
          ]}
        />
        <DatePicker.RangePicker
          onChange={(dates) =>
            setDateRange(dates ? [dates[0]!, dates[1]!] : null)
          }
          format="MMM D, YYYY"
        />
      </div>

      <Table
        dataSource={rows}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 50, showSizeChanger: true }}
        columns={[
          {
            title: "Host",
            key: "host",
            render: (_, r) => (
              <div>
                <div className="font-medium">{r.host_name}</div>
                <div className="text-xs text-gray-500">{r.host_email}</div>
              </div>
            ),
            sorter: (a, b) => a.host_name.localeCompare(b.host_name),
          },
          {
            title: "Guest",
            dataIndex: "guest_name",
            key: "guest_name",
            sorter: (a, b) => a.guest_name.localeCompare(b.guest_name),
          },
          {
            title: "Vehicle",
            key: "vehicle",
            render: (_, r) =>
              r.guest_plate
                ? `${r.guest_plate} (${r.guest_plate_state})`
                : <span className="text-gray-400">None</span>,
          },
          {
            title: "Check-in",
            dataIndex: "check_in",
            key: "check_in",
            render: (v: string) => dayjs(v).format("MMM D, YYYY"),
            sorter: (a, b) => a.check_in.localeCompare(b.check_in),
          },
          {
            title: "Check-out",
            dataIndex: "check_out",
            key: "check_out",
            render: (v: string) => dayjs(v).format("MMM D, YYYY"),
          },
          {
            title: "Status",
            dataIndex: "status",
            key: "status",
            render: (v: string) => {
              if (v === "cancelled") return <Tag color="red">Cancelled</Tag>;
              return <Tag color="green">Active</Tag>;
            },
          },
          {
            title: "Registered",
            dataIndex: "created_at",
            key: "created_at",
            render: (v: string) => v ? dayjs(v).format("MMM D h:mm A") : "-",
            sorter: (a, b) => (a.created_at || "").localeCompare(b.created_at || ""),
          },
        ]}
      />
    </div>
  );
}
