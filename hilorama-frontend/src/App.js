import { useState } from "react";
import AppEmpacador from "./AppEmpacador";
import AdminApp from "./AdminApp";
import { API_URL } from "./config";



export default function App() {
  /* ======================
     ESTADO GLOBAL
  ====================== */
  const [usuario, setUsuario] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState(null);
  const [rol, setRol] = useState(null);
  const [mensaje, setMensaje] = useState("");
  const esMovilOTablet = window.innerWidth <= 1024;
  const esDesktop = window.innerWidth > 1024;

  // EMPACADOR → solo móvil o tablet
  if (rol === "EMPACADOR" && !esMovilOTablet) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <h2>📱 Acceso restringido</h2>
        <p>El módulo de empacador está diseñado solo para teléfonos y tablets.</p>
      </div>
    );
  }

  // ADMIN → solo desktop
  if (rol === "ADMIN" && !esDesktop) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        <h2>💻 Acceso restringido</h2>
        <p>El panel de administración solo está disponible en computadora.</p>
      </div>
    );
  }

  
  /* ======================
     LOGIN
  ====================== */
  const login = async () => {
    setMensaje("Validando credenciales...");

    try {
      const res = await fetch(`${API_URL}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usuario, password }),
      });

      const data = await res.json();
      console.log("LOGIN RESPONSE DEL BACKEND:", data);

      if (!res.ok) {
        setMensaje(data.error || "Error al iniciar sesión");
        return;
      }

      setToken(data.token);
      setRol(data.rol); // 👈 CLAVE
      setMensaje(`Bienvenido ${data.nombre}`);
    } catch (err) {
      setMensaje("No se pudo conectar al servidor");
    }
  };
  
  /* ======================
     LOGIN UI
  ====================== */
  if (!token) {
    return (
      <div style={styles.loginContainer}>
        <div style={styles.card}>
          <h1 style={styles.title}>Hilorama</h1>
          <p style={styles.subtitle}>Sistema de Empaque</p>

          <input
            placeholder="Usuario"
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            style={styles.input}
          />

          <input
            type="password"
            placeholder="Contraseña"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={styles.input}
          />

          <button onClick={login} style={styles.button}>
            Entrar
          </button>

          {mensaje && <p style={styles.message}>{mensaje}</p>}
        </div>
      </div>
    );
  }

  /* ======================
     REDIRECCIÓN POR ROL
  ====================== */
const rolNormalizado = rol?.toUpperCase();

if (rolNormalizado === "EMPACADOR") {
  return <AppEmpacador token={token} />;
}

if (rolNormalizado === "ADMIN") {
  return <AdminApp token={token} />;
}


  /* ======================
     FALLBACK
  ====================== */
  return (
    <div style={{ padding: 40 }}>
      <h2>Rol no reconocido</h2>
      <p>Contacta al administrador del sistema.</p>
    </div>
  );
}

/* ======================
   ESTILOS
====================== */
const styles = {
  loginContainer: {
    minHeight: "100vh",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    background: "linear-gradient(135deg, #111827, #1F2933)",
  },
  card: {
    background: "#ffffff",
    padding: 30,
    borderRadius: 12,
    width: 320,
    boxShadow: "0 10px 25px rgba(0,0,0,0.25)",
    textAlign: "center",
  },
  title: {
    margin: 0,
    fontSize: 28,
    fontWeight: "bold",
    color: "#111827",
  },
  subtitle: {
    marginBottom: 20,
    color: "#6B7280",
  },
  input: {
    width: "100%",
    padding: 12,
    marginBottom: 12,
    borderRadius: 8,
    border: "1px solid #D1D5DB",
    fontSize: 14,
  },
  button: {
    width: "100%",
    padding: 12,
    background: "#111827",
    color: "#ffffff",
    border: "none",
    borderRadius: 8,
    fontWeight: "bold",
    cursor: "pointer",
  },
  message: {
    marginTop: 15,
    fontSize: 14,
    color: "#DC2626",
  },
};
  