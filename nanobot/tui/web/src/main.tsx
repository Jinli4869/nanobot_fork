import ReactDOM from "react-dom/client";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing root element");
}

function App() {
  return (
    <main>
      <h1>Nanobot Workspace</h1>
      <p>Frontend shell bootstrap in progress.</p>
    </main>
  );
}

ReactDOM.createRoot(root).render(<App />);
