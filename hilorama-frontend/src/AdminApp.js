import { useEffect, useState } from "react";
import { API_URL } from "./config";




const motivoColor = {
  NO_PERTENECE: "#DC2626",
  PIEZAS_COMPLETAS: "#F59E0B",
  NOTA_COMPLETA: "#7C2D12",
};

export default function AdminApp({ token }) {
  const [errores, setErrores] = useState([]);
  const [filtroNota, setFiltroNota] = useState("");
  const [filtroEmpacador, setFiltroEmpacador] = useState("");

  /* ======================
     CARGAR ERRORES
  ====================== */
  useEffect(() => {
    if (!token) return;

    fetch(`${API_URL}/errores-scan`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setErrores(data);
        } else {
          console.error("Respuesta inválida:", data);
          setErrores([]); // protección
        }
      });
  }, [token]);

  /* ======================
     FILTROS
  ====================== */
  const erroresFiltrados = errores.filter((e) => {
    return (
      (!filtroNota || e.nota_id.includes(filtroNota)) &&
      (!filtroEmpacador || e.empacador.includes(filtroEmpacador))
    );
  });

  return (
    <div style={{ padding: 20 }}>
      <h1>📊 Panel de errores de escaneo</h1>

      {/* Filtros */}
      <div style={{ display: "flex", gap: 10, marginBottom: 15 }}>
        <input
          placeholder="Filtrar por nota"
          value={filtroNota}
          onChange={(e) => setFiltroNota(e.target.value)}
        />
        <input
          placeholder="Filtrar por empacador"
          value={filtroEmpacador}
          onChange={(e) => setFiltroEmpacador(e.target.value)}
        />
      </div>

      {/* Sin errores */}
      {erroresFiltrados.length === 0 && (
        <div style={{ color: "#6B7280", marginTop: 10 }}>
          ✅ No hay errores registrados
        </div>
      )}

      {/* Lista de errores */}
      {erroresFiltrados.map((e, i) => (
        <div
          key={i}
          style={{
            marginBottom: 10,
            padding: 12,
            borderRadius: 10,
            background: "#F9FAFB",
            borderLeft: `6px solid ${motivoColor[e.motivo] || "#9CA3AF"}`,
          }}
        >
          <strong>Nota:</strong> {e.nota_id}<br />
          <strong>Empacador:</strong> {e.empacador}<br />
          <strong>Código:</strong> {e.codigo}<br />
          <strong>Motivo:</strong> {e.motivo}<br />
          <small>{e.fecha}</small>
        </div>
      ))}
    </div>
  );
}
