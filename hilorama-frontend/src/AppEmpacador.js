import { useEffect, useState } from "react";

const beepOk = () => {
  const audio = new Audio("https://actions.google.com/sounds/v1/cartoon/clang_and_wobble.ogg");
  audio.play();
};

const beepError = () => {
  const audio = new Audio("https://actions.google.com/sounds/v1/cartoon/wood_plank_flicks.ogg");
  audio.play();
};

const API = "https://hilorama-backend.onrender.com";

const coloresEstado = {
  EN_PROCESO: "#FACC15",
  INCOMPLETA: "#DC2626",
  COMPLETA: "#16A34A",
};




function BarraProgreso({ porcentaje, estado }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div
        style={{
          width: "100%",
          height: 14,
          background: "#E5E7EB",
          borderRadius: 10,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${porcentaje}%`,
            height: "100%",
            background: coloresEstado[estado],
            transition: "width 0.3s ease",
          }}
        />
      </div>
      <small>{porcentaje}% completado</small>
    </div>
  );
}

function App() {
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(null);
  const [mensaje, setMensaje] = useState("");
  const [tema, setTema] = useState("auto"); 
// "claro" | "oscuro" | "auto"
  const [notas, setNotas] = useState([]);
  const [notaActiva, setNotaActiva] = useState(null);
  const [progreso, setProgreso] = useState(0);
  const [scan, setScan] = useState("");
  const [scanMensaje, setScanMensaje] = useState("");
  const [productoError, setProductoError] = useState(null);
  const esOscuroSistema = window.matchMedia &&
  window.matchMedia("(prefers-color-scheme: dark)").matches;

  const modoOscuro =
  tema === "oscuro" || (tema === "auto" && esOscuroSistema);

  const estilosAnimacion = `
  @keyframes shake {
    0% { transform: translateX(0); }
    25% { transform: translateX(-4px); }
    50% { transform: translateX(4px); }
    75% { transform: translateX(-4px); }
    100% { transform: translateX(0); }
  }
  `;
  const colores = {
    fondo: modoOscuro ? "#111827" : "#F9FAFB",
    tarjeta: modoOscuro ? "#1F2937" : "#FFFFFF",
    texto: modoOscuro ? "#F9FAFB" : "#111827",
    borde: modoOscuro ? "#374151" : "#E5E7EB",
    boton: modoOscuro ? "#2563EB" : "#111827",
  };

  /* ======================
     LOGIN
  ====================== */
  const login = async () => {
    const res = await fetch(`${API}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario, password }),
    });

    const data = await res.json();
    if (!res.ok) {
      setMensaje(data.error);
      return;
    }

    setToken(data.token);
    setMensaje(`Bienvenido ${data.nombre}`);
  };
  const actualizarProgreso = async (id) => {
    const res = await fetch(`${API}/notas/${id}/progreso`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    const data = await res.json();
    setProgreso(data.porcentaje);
  };
  const enviarScan = async (codigo) => {
    const res = await fetch(
      `${API}/notas/${notaActiva.id}/scan`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ codigo }),
      }
    );

    const data = await res.json();

    if (!res.ok) {
      setScanMensaje(data.error || "Error de escaneo");
      beepError();
      // 👇 marcar producto en error
      setProductoError(codigo);
      // 👇 quitar el parpadeo después de 1s
      setTimeout(() => setProductoError(null), 2000);
      return;
    }
    beepOk();

    setScanMensaje("✔ Producto agregado");
    setTimeout(() => setScanMensaje(""), 1500);

    setNotaActiva({
      
      ...notaActiva,
      estado: data.estado_nota,
      productos: notaActiva.productos.map((p) =>
        p.codigo === data.producto.codigo ? data.producto : p
      ),
    });
    actualizarProgreso(notaActiva.id);  
  };   
  
  /* ======================
     CARGAR NOTAS
  ====================== */
  useEffect(() => {
    if (!token) return;

    fetch(`${API}/notas-pagadas`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.json())
      .then((data) => {
        if (Array.isArray(data)) {
          setNotas(data);
        } else {
          console.error("Respuesta inválida:", data);
          setNotas([]); // 🔐 evita el crash
        }
      });

  }, [token]);

  /* ======================
     PROGRESO NOTA
  ====================== */
  useEffect(() => {
    if (!notaActiva) return;

    fetch(`${API}/notas/${notaActiva.id}/progreso`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => res.json())
      .then((data) => setProgreso(data.porcentaje));
  }, [notaActiva, token]);

  /* ======================
     AJUSTAR PRODUCTO
  ====================== */
  const ajustar = async (codigo, cantidad) => {
    const res = await fetch(
      `${API}/notas/${notaActiva.id}/producto/ajustar`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ codigo, cantidad }),
      }
    );

    const data = await res.json();
    if (!res.ok) {
      alert(data.error);
      return;
    }

    const nuevaNota = {
      ...notaActiva,
      estado: data.estado_nota,
      productos: notaActiva.productos.map((p) =>
        p.codigo === data.producto.codigo ? data.producto : p
      ),
    };

    setNotaActiva(nuevaNota);
    setNotas(notas.map(n => n.id === nuevaNota.id ? nuevaNota : n));
    actualizarProgreso(notaActiva.id);
  };


  
  /* ======================
     REINICIAR NOTA
  ====================== */
  const reiniciarNota = async () => {
    if (!window.confirm("¿Reiniciar toda la nota?")) return;

    const res = await fetch(
      `${API}/notas/${notaActiva.id}/reset`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }
    );

    const data = await res.json();
    setNotaActiva(data);
    setNotas(notas.map(n => n.id === data.id ? data : n));
  };

  /* ======================
     LOGIN UI
  ====================== */
  if (!token) {
    return (
      <div style={{ maxWidth: 400, margin: "auto", padding: 30 }}>
        <h1>Hilorama</h1>

        <input
          placeholder="Usuario"
          value={usuario}
          onChange={(e) => setUsuario(e.target.value)}
          style={{ width: "100%", padding: 10 }}
        />
        <br /><br />

        <input
          type="password"
          placeholder="Contraseña"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ width: "100%", padding: 10 }}
        />
        <br /><br />

        <button
          onClick={login}
          style={{
            width: "100%",
            padding: 12,
            background: "#111827",
            color: "#fff",
            borderRadius: 8,
          }}
        >
          Entrar
        </button>

        <p>{mensaje}</p>
      </div>
    );
  }

  /* ======================
     NOTA ABIERTA
  ====================== */
  if (notaActiva) {
    return (


      <div
        style={{
          padding: "16px 12px",
          maxWidth: 480,
          margin: "0 auto",
          minHeight: "100vh",
          background: colores.fondo,
          color: colores.texto,
        }}
      >

        <div style={{ maxWidth: 480, margin: "auto" }}></div>
        <h2>{notaActiva.id}</h2>
        <p><strong>Cliente:</strong> {notaActiva.cliente}</p>
        <p><strong>Estado:</strong> {notaActiva.estado}</p>
        <div style={{ marginBottom: 15 }}>
          <select
            value={tema}
            onChange={(e) => setTema(e.target.value)}
            style={{
              width: "100%",
              padding: 12,
              borderRadius: 10,
              border: `1px solid ${colores.borde}`,
              background: colores.tarjeta,
              color: colores.texto,
              fontWeight: "bold",
            }}
          >
            <option value="auto">🌗 Automático</option>
            <option value="claro">☀️ Claro</option>
            <option value="oscuro">🌙 Oscuro</option>
          </select>
        </div>

     


        <BarraProgreso
          porcentaje={progreso}
          estado={notaActiva.estado}
        />
        {notaActiva.estado === "COMPLETA" && (
          <div style={{
            marginTop: 10,
            padding: 10,
            background: "#DCFCE7",
            color: "#166534",
            borderRadius: 8,
            fontWeight: "bold"
          }}>
            ✅ Nota completada correctamente
          </div>
        )}

        <div style={{ marginTop: 15 }}>
          <input
            autoFocus
            disabled={notaActiva.estado === "COMPLETA"}
            placeholder={
              notaActiva.estado === "COMPLETA"
                ? "Nota completada"
                : "Escanea el código..."
            }
            value={scan}
            onChange={(e) => setScan(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && notaActiva.estado !== "COMPLETA") {
                enviarScan(scan.trim());
                setScan("");
              }
            }}
            style={{
              width: "100%",
              padding: 12,
              fontSize: 16,
              borderRadius: 8,
              border: "2px solid #111827",
              background: notaActiva.estado === "COMPLETA" ? "#E5E7EB" : "#fff",
              cursor: notaActiva.estado === "COMPLETA" ? "not-allowed" : "text",
            }}
          />

          <small style={{ color: "#374151" }}>
            Escanea el código de barras (ENTER automático)
          </small>

          {scanMensaje && (
            <div
              style={{
                marginTop: 5,
                color: scanMensaje.startsWith("✔") ? "#16A34A" : "#DC2626",
              }}
            >
              {scanMensaje}
            </div>
          )}
        </div>
  
        {notaActiva.productos.map((p) => {
          const completo = p.pz_empacadas === p.pz_requeridas;
          const enError = productoError === p.codigo;

          return (
            <div
              key={p.codigo}
              style={{
                marginTop: 16,
                padding: 18,
                borderRadius: 14,
                background: p.pz_empacadas === p.pz_requeridas
                  ? "#DCFCE7"
                  : colores.tarjeta,
                border: p.pz_empacadas === p.pz_requeridas
                  ? "2px solid #16A34A"
                  : "1px solid #E5E7EB",
                boxShadow: "0 6px 16px rgba(0,0,0,0.08)",
           

              }}
            >
              <strong>{p.codigo}</strong>

              <div>
                {p.pz_empacadas} / {p.pz_requeridas}
              </div>

              {completo && (
                <div
                  style={{
                    marginTop: 6,
                    color: "#166534",
                    fontWeight: "bold",
                    fontSize: 14,
                  }}
                >
                  ✔ Producto completo
                </div>
              )}

              {enError && (
                <div
                  style={{
                    marginTop: 6,
                    color: "#DC2626",
                    fontWeight: "bold",
                    fontSize: 14,
                  }}
                >
                  ⚠ Producto lleno / inválido
                </div>
              )}

              <div style={{ marginTop: 8 }}>
                <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
                  <button
                    onClick={() => ajustar(p.codigo, -1)}
                    style={{
                      flex: 1,
                      padding: "14px 0",
                      fontSize: 22,
                      fontWeight: "bold",
                      borderRadius: 12,
                      border: "none",
                      background: "#DC2626",
                      color: "#fff",
                      boxShadow: "0 4px 10px rgba(0,0,0,0.15)",
                      cursor: "pointer",
                    }}
                  >
                    −
                  </button>

                  <button
                    onClick={() => ajustar(p.codigo, 1)}
                    style={{
                      flex: 1,
                      padding: "14px 0",
                      fontSize: 22,
                      fontWeight: "bold",
                      borderRadius: 12,
                      border: "none",
                      background: "#16A34A",
                      color: "#fff",
                      boxShadow: "0 4px 10px rgba(0,0,0,0.15)",
                      cursor: "pointer",
                    }}
                  >
                    +
                  </button>
                </div>

              </div>
            </div>
          );
        })}



        <button
          onClick={reiniciarNota}
          style={{
            marginTop: 20,
            width: "100%",
            padding: 12,
            background: "#DC2626",
            color: "#fff",
            borderRadius: 8,
          }}
        >
          Reiniciar nota completa
        </button>

        <br /><br />
        <button
          onClick={() => setNotaActiva(null)}
          style={{
            marginTop: 20,
            width: "100%",
            padding: 14,
            fontSize: 16,
            fontWeight: "bold",
            borderRadius: 12,
            border: "none",
            background: "#111827",
            color: "#fff",
            boxShadow: "0 6px 16px rgba(0,0,0,0.2)",
            cursor: "pointer",
          }}
        >
         ⬅ Volver a notas
        </button>

      </div>
    );
  }

  /* ======================
     LISTA DE NOTAS
  ====================== */
  return (
    <div style={{ padding: 20 }}>
      <h1>Notas asignadas</h1>

      {Array.isArray(notas) && notas.map((nota) => (
        <div
          key={nota.id}
          onClick={() => setNotaActiva(nota)}
          style={{
            cursor: "pointer",
            padding: 15,
            borderRadius: 10,
            marginBottom: 12,
            background: coloresEstado[nota.estado],
          }}
        >
          <strong>{nota.id}</strong><br />
          Cliente: {nota.cliente}<br />
          Estado: {nota.estado}
        </div>
      ))}
    </div>
  );
}

export default App;




