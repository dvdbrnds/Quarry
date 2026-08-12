import { useCallback, useEffect, useState } from "react";
import { Button, Table, App, Tag } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { authHeaders } from "../auth";
import dayjs from "dayjs";

interface VoucherUsageEntry {
  id: string;
  voucher_code: string;
  program_name: string;
  student_name: string;
  student_email: string;
  student_id: string;
  permit_type_code: string;
  original_price: number;
  discount_amount: number;
  final_price: number;
  used_at: string;
}

export default function ChargebackLog() {
  const { message } = App.useApp();
  const [usages, setUsages] = useState<VoucherUsageEntry[]>([]);
  const [usagesLoading, setUsagesLoading] = useState(false);

  const loadUsages = useCallback(async () => {
    setUsagesLoading(true);
    try {
      const res = await fetch("/api/vouchers/usages", { headers: await authHeaders() });
      if (res.ok) setUsages(await res.json());
    } catch { /* silent */ }
    finally { setUsagesLoading(false); }
  }, []);

  useEffect(() => { loadUsages(); }, [loadUsages]);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold m-0">Department Chargebacks</h2>
          <p className="text-sm text-gray-500 m-0 mt-1">
            Voucher usage log — send to departments for reimbursement
          </p>
        </div>
        <Button
          icon={<DownloadOutlined />}
          onClick={async () => {
            const headers = await authHeaders();
            const res = await fetch("/api/vouchers/usages/export", { headers });
            if (!res.ok) { message.error("Export failed"); return; }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "voucher_chargebacks.csv";
            a.click();
            URL.revokeObjectURL(url);
          }}
          disabled={usages.length === 0}
        >
          Export CSV
        </Button>
      </div>

      <Table
        dataSource={usages}
        rowKey="id"
        loading={usagesLoading}
        size="small"
        pagination={{ defaultPageSize: 15, showSizeChanger: true }}
        columns={[
          {
            title: "Date",
            dataIndex: "used_at",
            key: "used_at",
            width: 130,
            render: (v: string) => dayjs(v).format("MMM D, YYYY"),
          },
          { title: "Code", dataIndex: "voucher_code", key: "voucher_code", width: 130, render: (v: string) => <code>{v}</code> },
          { title: "Program", dataIndex: "program_name", key: "program_name" },
          { title: "Student", dataIndex: "student_name", key: "student_name" },
          { title: "Email", dataIndex: "student_email", key: "student_email" },
          { title: "Permit", dataIndex: "permit_type_code", key: "permit_type_code", width: 120 },
          {
            title: "Discount",
            dataIndex: "discount_amount",
            key: "discount_amount",
            width: 100,
            render: (v: number) => <span className="font-medium text-red-600">${v.toFixed(2)}</span>,
          },
          {
            title: "Charged",
            dataIndex: "final_price",
            key: "final_price",
            width: 90,
            render: (v: number) => v > 0 ? `$${v.toFixed(2)}` : <Tag color="green">FREE</Tag>,
          },
        ]}
      />
    </div>
  );
}
