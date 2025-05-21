export async function generateTour(prompt) {
    const apiKey = import.meta.env.VITE_OPENAI_API_KEY;
  
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "gpt-4",
        messages: [
          {
            role: "system",
            content: "You are a helpful AI tour guide assistant.",
          },
          {
            role: "user",
            content: prompt,
          },
        ],
        temperature: 0.7,
      }),
    });
  
    const data = await response.json();
  
    if (!response.ok) {
      throw new Error(data.error?.message || "Failed to generate tour");
    }
  
    return data.choices[0].message.content;
  }
  