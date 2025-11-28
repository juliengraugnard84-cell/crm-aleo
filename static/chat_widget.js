// OUVERTURE / FERMETURE
const btn = document.getElementById("chat-widget-button");
const box = document.getElementById("chat-widget-window");
const closeBtn = document.getElementById("chat-widget-close");

btn.onclick = () => box.classList.remove("hidden");
closeBtn.onclick = () => box.classList.add("hidden");

// ENVOI DE MESSAGE
const input = document.getElementById("chat-widget-input");
const sendBtn = document.getElementById("chat-widget-send");
const msgBox = document.getElementById("chat-widget-messages");

async function sendMessage() {

    const text = input.value.trim();
    if (!text) return;

    // Afficher message utilisateur
    msgBox.innerHTML += `<div><strong>Moi :</strong> ${text}</div>`;
    msgBox.scrollTop = msgBox.scrollHeight;

    input.value = "";

    // Appeler l’API IA interne
    const response = await fetch("/chat_ai", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ message: text })
    });

    const data = await response.json();

    // Afficher réponse IA
    msgBox.innerHTML += `<div style="margin-top:6px;">
        <strong>🤖 IA :</strong> ${data.reply}
    </div>`;

    msgBox.scrollTop = msgBox.scrollHeight;
}

sendBtn.onclick = sendMessage;

input.addEventListener("keydown", e => {
    if (e.key === "Enter") sendMessage();
});
