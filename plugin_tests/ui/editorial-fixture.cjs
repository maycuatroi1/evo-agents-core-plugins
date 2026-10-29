// Fictional editorial data for DOM tests and the local preview. No user content or credentials.
const workspace = {
  stages: [
    { name: "idea", title: "Chọn chủ đề" },
    { name: "draft", title: "Đang viết" },
    { name: "review", title: "Chờ duyệt" },
    { name: "ship", title: "Đã xuất bản" },
  ],
  notebooks: [
    { name: "voice", title: "Giọng viết" },
    { name: "facts", title: "Nguồn và dữ kiện" },
  ],
};
const posts = [
  {
    slug: "northwind-first-topic",
    title: "Đề xuất chủ đề cho bản tin Northwind",
    stage: "idea",
    waiting_gate: "idea",
    rounds: 0,
  },
  {
    slug: "northwind-cache",
    title: "Vì sao cache vẫn trả dữ liệu cũ sau khi cập nhật?",
    stage: "draft",
    run: { state: "running" },
    rounds: 1,
  },
  {
    slug: "northwind-retries",
    title: "Một lần retry có thể tạo hai đơn hàng",
    stage: "review",
    waiting_gate: "review",
    rounds: 3,
    preview_url: "https://example.org/preview",
  },
  {
    slug: "northwind-observability",
    title: "Đọc log để tìm request thất bại trong chuỗi dịch vụ",
    stage: "review",
    waiting_gate: "review",
    rounds: 2,
    preview_url: "https://example.org/preview",
  },
  {
    slug: "northwind-database",
    title: "Kiểm tra bản sao lưu bằng một lần khôi phục",
    stage: "ship",
    rounds: 4,
    url: "https://example.org/post",
  },
];
const entries = Array.from({ length: 23 }, (_, i) => ({
  id: "PH-" + String(i + 1).padStart(4, "0"),
  notebook: i % 2 ? "facts" : "voice",
  title: [
    "Mở bài bằng vấn đề người đọc gặp",
    "Ghi ngày đo cho số liệu thay đổi nhanh",
    "Ví dụ phải có đầu vào và kết quả cụ thể",
    "Tách kết quả đo khỏi giả thuyết giải thích",
    "Dẫn nguồn ngay bên cạnh dữ kiện",
  ][i % 5],
  date: "2026-10-" + String(1 + i).padStart(2, "0"),
  post: i % 2 ? "northwind-retries" : null,
  seen: (i % 5) + 1,
  rule: "Nêu rõ ai gặp vấn đề, trong tình huống nào và điều gì đang xảy ra. Dùng một ví dụ cụ thể trước khi giải thích cơ chế; không mở bằng nhận xét chung về công nghệ.",
  check:
    "Đọc lại đoạn mở đầu và xác định người đọc, tình huống, tác động. Nếu chưa đủ thông tin, bổ sung từ nguồn đã kiểm tra.",
  said: [
    {
      text: "Đoạn mở đầu đang nói chung quá. Tôi chưa biết ai gặp vấn đề này và vì sao họ cần đọc tiếp.",
      date: "2026-10-01",
    },
  ],
  agent_wrote: i === 0 ? "Công nghệ đang thay đổi nhanh chóng." : null,
  person_fixed:
    i === 0
      ? "Request gửi lại sau timeout có thể tạo thêm một đơn hàng."
      : null,
}));
const post = {
  ...posts[2],
  branch: "post/northwind-retries",
  run: {
    state: "done",
    run_id: 42,
    stage: "review",
    at: "2026-10-20T08:00:00Z",
  },
  gates: [
    {
      stage: "idea",
      kind: "choose",
      state: "answered",
      answered_at: "2026-10-18T08:00:00Z",
      answered_via: "hub",
      answered_by: "reviewer",
    },
    { stage: "review", kind: "comments", state: "waiting" },
  ],
  rounds: [1, 2, 3].map((number) => ({
    number,
    stage: "review",
    at: `2026-10-${17 + number}T08:00:00Z`,
    note: "Bổ sung ví dụ request gửi lại, đối chiếu kết quả với log và thêm nguồn cho các thông số.",
    feedback: ["PH-0001"],
    judge: {
      state: "passed",
      note: "Ví dụ có kết quả kiểm tra và nguồn đối chiếu.",
    },
    scores: { slop: 4, giong: 5, nguon: 4, hinh: 4 },
    comments: [
      {
        author: "Reviewer",
        quote: "Retry luôn an toàn.",
        text: "Cần nói rõ điều kiện: thao tác phải có idempotency key.",
      },
    ],
  })),
  history: workspace.stages
    .slice(0, 3)
    .map((stage, i) => ({
      stage: stage.name,
      at: `2026-10-${18 + i}T08:00:00Z`,
    })),
  feedback: ["PH-0001", "PH-0002"],
};
module.exports = { workspace, posts, entries, post };
