import { useEffect, useState } from "react";
import { Table, Card, Tag, Statistic, Row, Col } from "antd";
import { getAccessToken } from "../auth";

interface PlateCorrection {
  id: string;
  ocr_plate: string;
  correct_plate: string;
  plate_state: string;
  lot: string;
  officer_name: string;
  officer_email: string;
  device_name: string;
  notes: string;
  created_at: string;
}

export default function PlateCorrections() {
  const [data, setData] = useState<PlateCorrection[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const token = await getAccessToken();
        const res = await fetch("/api/audit/plate-corrections?limit=500", {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (res.ok) setData(await res.json());
      } catch {
        /* ignore */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const charDiffs = data.map((c) => {
    const ocr = c.ocr_plate.toUpperCase();
    const correct = c.correct_plate.toUpperCase();
    const diffs: string[] = [];
    const len = Math.max(ocr.length, correct.length);
    for (let i = 0; i < len; i++) {
      if ((ocr[i] || "") !== (correct[i] || "")) {
        diffs.push(`${ocr[i] || "∅"}→${correct[i] || "∅"}`);
      }
    }
    return diffs;
  });

  const confusionCounts: Record<string, number> = {};
  charDiffs.forEach((diffs) => {
    diffs.forEach((d) => {
      confusionCounts[d] = (confusionCounts[d] || 0) + 1;
    });
  });
  const topConfusions = Object.entries(confusionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);

  const columns = [
    {
      title: "Time",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (v: string) =>
        new Date(v).toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        }),
    },
    {
      title: "OCR Read",
      dataIndex: "ocr_plate",
      key: "ocr_plate",
      render: (v: string) => (
        <span style={{ fontFamily: "monospace", color: "#cf1322", fontWeight: 600 }}>{v}</span>
      ),
    },
    {
      title: "",
      key: "arrow",
      width: 40,
      render: () => <span style={{ color: "#999" }}>→</span>,
    },
    {
      title: "Correct Plate",
      dataIndex: "correct_plate",
      key: "correct_plate",
      render: (v: string) => (
        <span style={{ fontFamily: "monospace", color: "#389e0d", fontWeight: 600 }}>{v}</span>
      ),
    },
    {
      title: "Diff",
      key: "diff",
      render: (_: unknown, __: unknown, idx: number) =>
        (charDiffs[idx] || []).map((d, i) => (
          <Tag key={i} color="orange">
            {d}
          </Tag>
        )),
    },
    { title: "Lot", dataIndex: "lot", key: "lot", width: 100 },
    { title: "Officer", dataIndex: "officer_name", key: "officer_name", width: 150 },
    { title: "Notes", dataIndex: "notes", key: "notes", ellipsis: true },
  ];

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="Total Corrections" value={data.length} />
          </Card>
        </Col>
        <Col span={18}>
          <Card size="small" title="Top OCR Confusions">
            {topConfusions.length === 0 ? (
              <span style={{ color: "#999" }}>No data yet</span>
            ) : (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {topConfusions.map(([pair, count]) => (
                  <Tag key={pair} color="volcano">
                    {pair} × {count}
                  </Tag>
                ))}
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Table
        dataSource={data}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        pagination={{ pageSize: 50 }}
      />
    </div>
  );
}
