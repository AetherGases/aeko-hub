db = db.getSiblingDB("aether");

// -------------------------------------------------------------
// Limpa as coleções antes de popular (idempotente)
// -------------------------------------------------------------
[
  "user",
  "user_memory",
  "session",
  "input_report_analysis",
  "web_search",
  "improvement_plan",
].forEach((c) => db[c].drop());

// -------------------------------------------------------------
// 1) user
// -------------------------------------------------------------
const userIds = [
  ObjectId("650000000000000000000001"),
  ObjectId("650000000000000000000002"),
  ObjectId("650000000000000000000003"),
  ObjectId("650000000000000000000004"),
  ObjectId("650000000000000000000005"),
];

db.user.insertMany([
  {
    _id: userIds[0],
    id_external_user: 1001,
    role: "admin",
    usecase: "gas_reduction_analysis",
  },
  {
    _id: userIds[1],
    id_external_user: 1002,
    role: "analyst",
    usecase: "gas_reduction_analysis",
  },
  {
    _id: userIds[2],
    id_external_user: 1003,
    role: "viewer",
    usecase: "gas_reduction_analysis",
  },
  {
    _id: userIds[3],
    id_external_user: 1004,
    role: "analyst",
    usecase: "emissions_report_review",
  },
  {
    _id: userIds[4],
    id_external_user: 1005,
    role: "admin",
    usecase: "emissions_report_review",
  },
]);

// -------------------------------------------------------------
// 2) user_memory  (memória permanente por usuário)
// -------------------------------------------------------------
db.user_memory.insertMany([
  {
    _id: ObjectId("650000000000000000000101"),
    id_user: userIds[0],
    field: "preferred_language",
    description: "Usuário prefere respostas em português técnico, direto ao ponto.",
    created_at: new Date("2026-07-10T09:00:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000102"),
    id_user: userIds[0],
    field: "last_topic",
    description: "Última sessão tratou de redução de CH4 em plantas de tratamento de efluentes.",
    created_at: new Date("2026-07-15T14:30:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000103"),
    id_user: userIds[1],
    field: "preferred_units",
    description: "Usuário sempre reporta emissões em toneladas métricas de CO2e.",
    created_at: new Date("2026-07-11T11:15:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000104"),
    id_user: userIds[2],
    field: "focus_area",
    description: "Foco principal em relatórios de emissão de N2O em processos industriais.",
    created_at: new Date("2026-07-12T08:45:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000105"),
    id_user: userIds[3],
    field: "recurring_request",
    description: "Costuma pedir planos de melhoria comparando métodos de mitigação diferentes.",
    created_at: new Date("2026-07-16T17:20:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000106"),
    id_user: userIds[4],
    field: "last_session_summary",
    description: "Última sessão gerou plano de melhoria para redução de SF6 em subestações.",
    created_at: new Date("2026-07-17T19:05:00Z"),
  },
]);

// -------------------------------------------------------------
// 3) session (com array embutido de messages)
// -------------------------------------------------------------
db.session.insertMany([
  {
    _id: ObjectId("650000000000000000000201"),
    id_user: userIds[0],
    name: "Sessão - Redução de CH4 em ETE",
    messages: [
      {
        input: "Quais são as principais fontes de metano na estação de tratamento?",
        ouput:
          "As principais fontes são os tanques anaeróbios e a digestão de lodo.",
        submitted_at: new Date("2026-07-15T14:00:00Z"),
        llm: "claude-sonnet-5",
        input_tokens: 32,
        output_tokens: 87,
      },
      {
        input: "Como podemos reduzir essa emissão em 20%?",
        ouput:
          "Recomenda-se captura de biogás com queima em flare e uso do gás para geração de energia.",
        submitted_at: new Date("2026-07-15T14:05:00Z"),
        llm: "claude-sonnet-5",
        input_tokens: 28,
        output_tokens: 110,
      },
    ],
  },
  {
    _id: ObjectId("650000000000000000000202"),
    id_user: userIds[1],
    name: "Sessão - Relatório de emissões Q2",
    messages: [
      {
        input: "Compare as emissões de CO2 do Q1 e Q2.",
        ouput: "O Q2 apresentou queda de 8% em relação ao Q1, principalmente pela troca de combustível.",
        submitted_at: new Date("2026-07-11T11:00:00Z"),
        llm: "claude-sonnet-5",
        input_tokens: 40,
        output_tokens: 95,
      },
    ],
  },
  {
    _id: ObjectId("650000000000000000000203"),
    id_user: userIds[2],
    name: "Sessão - Emissões de N2O",
    messages: [
      {
        input: "Qual o impacto do N2O no processo de fertilização industrial?",
        ouput: "O N2O tem potencial de aquecimento global 273x maior que o CO2 no horizonte de 100 anos.",
        submitted_at: new Date("2026-07-12T08:30:00Z"),
        llm: "claude-opus-4-8",
        input_tokens: 35,
        output_tokens: 102,
      },
      {
        input: "Existe alguma tecnologia de abatimento catalítico recomendada?",
        ouput: "Sim, catalisadores de zeólita têm mostrado eficiência acima de 90% em testes de campo.",
        submitted_at: new Date("2026-07-12T08:40:00Z"),
        llm: "claude-opus-4-8",
        input_tokens: 30,
        output_tokens: 88,
      },
    ],
  },
  {
    _id: ObjectId("650000000000000000000204"),
    id_user: userIds[3],
    name: "Sessão - Plano de mitigação SF6",
    messages: [
      {
        input: "Preciso de um plano de melhoria para reduzir vazamento de SF6 em subestações.",
        ouput: "Plano gerado com foco em manutenção preditiva e substituição de gaxetas.",
        submitted_at: new Date("2026-07-16T17:00:00Z"),
        llm: "claude-sonnet-5",
        input_tokens: 45,
        output_tokens: 130,
      },
    ],
  },
  {
    _id: ObjectId("650000000000000000000205"),
    id_user: userIds[4],
    name: "Sessão - Revisão geral de relatórios",
    messages: [
      {
        input: "Revise o relatório de emissões consolidado do último trimestre.",
        ouput: "Relatório revisado; principais desvios identificados nas fontes fugitivas.",
        submitted_at: new Date("2026-07-17T19:00:00Z"),
        llm: "claude-opus-4-8",
        input_tokens: 50,
        output_tokens: 140,
      },
      {
        input: "Gere um resumo executivo em 3 bullets.",
        ouput: "Resumo executivo gerado com os 3 principais pontos de atenção.",
        submitted_at: new Date("2026-07-17T19:10:00Z"),
        llm: "claude-opus-4-8",
        input_tokens: 20,
        output_tokens: 60,
      },
    ],
  },
]);

// -------------------------------------------------------------
// 4) input_report_analysis (com array embutido de observations)
// -------------------------------------------------------------
db.input_report_analysis.insertMany([
  {
    _id: ObjectId("650000000000000000000301"),
    id_external_report: 5001,
    gas: "CH4",
    emitted_tons: 128.45,
    observations: [
      { text: "Pico de emissão observado no turno noturno." },
      { text: "Correlação com falha no selo do digestor #3." },
    ],
    created_at: new Date("2026-07-15T13:00:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000302"),
    id_external_report: 5002,
    gas: "CO2",
    emitted_tons: 942.3,
    observations: [
      { text: "Aumento sazonal esperado devido à queima de biomassa." },
    ],
    created_at: new Date("2026-07-11T10:30:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000303"),
    id_external_report: 5003,
    gas: "N2O",
    emitted_tons: 15.7,
    observations: [
      { text: "Valores dentro do esperado para o processo de fertilização." },
      { text: "Recomenda-se monitoramento contínuo do catalisador." },
    ],
    created_at: new Date("2026-07-12T08:00:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000304"),
    id_external_report: 5004,
    gas: "SF6",
    emitted_tons: 3.2,
    observations: [
      { text: "Vazamento detectado na subestação B, célula 12." },
    ],
    created_at: new Date("2026-07-16T16:30:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000305"),
    id_external_report: 5005,
    gas: "CO2",
    emitted_tons: 501.9,
    observations: [
      { text: "Redução de 8% frente ao trimestre anterior." },
      { text: "Efeito atribuído à troca de combustível na frota." },
    ],
    created_at: new Date("2026-07-17T18:00:00Z"),
  },
]);

// -------------------------------------------------------------
// 5) web_search (com array embutido de results)
// -------------------------------------------------------------
db.web_search.insertMany([
  {
    _id: ObjectId("650000000000000000000401"),
    query: "melhores práticas captura de biogás ETE",
    results: [
      {
        source: "epa.gov",
        content: "Guia técnico sobre captura e aproveitamento de biogás em estações de tratamento.",
        published_at: new Date("2026-03-01T00:00:00Z"),
      },
      {
        source: "iea.org",
        content: "Relatório da IEA sobre tecnologias de mitigação de metano no setor de saneamento.",
        published_at: new Date("2026-05-14T00:00:00Z"),
      },
    ],
    created_at: new Date("2026-07-15T14:02:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000402"),
    query: "tendências de emissões de CO2 setor industrial 2026",
    results: [
      {
        source: "iea.org",
        content: "Panorama global de emissões industriais com projeções até 2030.",
        published_at: new Date("2026-06-20T00:00:00Z"),
      },
    ],
    created_at: new Date("2026-07-11T11:02:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000403"),
    query: "catalisadores zeólita abatimento N2O",
    results: [
      {
        source: "sciencedirect.com",
        content: "Estudo sobre eficiência de catalisadores de zeólita na redução de N2O.",
        published_at: new Date("2026-02-10T00:00:00Z"),
      },
      {
        source: "researchgate.net",
        content: "Comparativo entre tecnologias catalíticas para abatimento de óxido nitroso.",
        published_at: new Date("2026-04-05T00:00:00Z"),
      },
    ],
    created_at: new Date("2026-07-12T08:42:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000404"),
    query: "manutenção preditiva vazamento SF6 subestações",
    results: [
      {
        source: "ieee.org",
        content: "Artigo técnico sobre detecção precoce de vazamentos de SF6 via sensores acústicos.",
        published_at: new Date("2026-05-30T00:00:00Z"),
      },
    ],
    created_at: new Date("2026-07-16T17:01:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000405"),
    query: "resumo executivo relatório de emissões trimestral",
    results: [
      {
        source: "ghgprotocol.org",
        content: "Modelo padrão para elaboração de resumos executivos de relatórios de GEE.",
        published_at: new Date("2026-01-15T00:00:00Z"),
      },
      {
        source: "cdp.net",
        content: "Boas práticas de divulgação de emissões para stakeholders.",
        published_at: new Date("2026-06-01T00:00:00Z"),
      },
    ],
    created_at: new Date("2026-07-17T19:11:00Z"),
  },
]);

// -------------------------------------------------------------
// 6) improvement_plan
// -------------------------------------------------------------
db.improvement_plan.insertMany([
  {
    _id: ObjectId("650000000000000000000501"),
    id_external_gas_reduction: 9001,
    defined_problem: "Emissão elevada de CH4 no digestor anaeróbio #3.",
    method: "Captura de biogás com queima em flare e cogeração de energia.",
    reasoning: "Reduz emissão direta e ainda gera valor energético reaproveitável.",
    updated_at: new Date("2026-07-15T14:10:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000502"),
    id_external_gas_reduction: 9002,
    defined_problem: "Aumento sazonal de CO2 pela queima de biomassa.",
    method: "Substituição parcial por gás natural em períodos de pico.",
    reasoning: "Gás natural tem fator de emissão menor por unidade de energia gerada.",
    updated_at: new Date("2026-07-11T11:20:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000503"),
    id_external_gas_reduction: 9003,
    defined_problem: "Emissão de N2O acima da meta no processo de fertilização.",
    method: "Instalação de catalisadores de zeólita nas linhas de exaustão.",
    reasoning: "Testes de campo indicam eficiência de abatimento acima de 90%.",
    updated_at: new Date("2026-07-12T08:50:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000504"),
    id_external_gas_reduction: 9004,
    defined_problem: "Vazamento recorrente de SF6 na subestação B.",
    method: "Manutenção preditiva com sensores acústicos e substituição de gaxetas.",
    reasoning: "Detecção precoce evita vazamentos maiores e reduz custo de reposição de gás.",
    updated_at: new Date("2026-07-16T17:25:00Z"),
  },
  {
    _id: ObjectId("650000000000000000000505"),
    id_external_gas_reduction: 9005,
    defined_problem: "Falta de padronização nos relatórios trimestrais de GEE.",
    method: "Adoção de template baseado no GHG Protocol para todos os relatórios.",
    reasoning: "Padronização facilita comparação histórica e auditoria externa.",
    updated_at: new Date("2026-07-17T19:15:00Z"),
  },
]);

// -------------------------------------------------------------
// Índices TTL (conforme anotações do diagrama)
// -------------------------------------------------------------
// user_memory -> expira 12 dias após created_at
db.user_memory.createIndex(
  { created_at: 1 },
  { expireAfterSeconds: 12 * 24 * 60 * 60, name: "ttl_user_memory_12d" }
);

// web_search -> expira 7 dias após created_at
db.web_search.createIndex(
  { created_at: 1 },
  { expireAfterSeconds: 7 * 24 * 60 * 60, name: "ttl_web_search_7d" }
);

// -------------------------------------------------------------
// Índices auxiliares de relacionamento (não-TTL, boa prática)
// -------------------------------------------------------------
db.user_memory.createIndex({ id_user: 1 });
db.session.createIndex({ id_user: 1 });
db.user.createIndex({ id_external_user: 1 }, { unique: true });
db.input_report_analysis.createIndex({ id_external_report: 1 });
db.improvement_plan.createIndex({ id_external_gas_reduction: 1 });