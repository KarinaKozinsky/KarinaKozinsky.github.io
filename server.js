import express from 'express';
import cors from 'cors';
import bodyParser from 'body-parser';
import { OpenAI } from 'openai';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
const port = 5000;
console.log('Server is running...')
// CORS options
const corsOptions = {
  origin: 'http://localhost:5173', // Allow requests from this origin
  methods: ['GET', 'POST'], // Allow specific HTTP methods
};

// Middleware
app.use(cors(corsOptions)); // Apply CORS middleware with the options
app.use(bodyParser.json());

// Initialize OpenAI client
const openai = new OpenAI({
  apiKey:process.env.OPENAI_API_KEY
});

// Route to handle tour generation
app.post('/generate-tour', async (req, res) => {
  const { city, themes, duration } = req.body;

  try {
    const response = await openai.chat.completions.create({
      model: 'gpt-3.5-turbo',
      messages: [
        {
          role: 'system',
          content: 'You are a helpful tour planning assistant.',
        },
        {
          role: 'user',
          content: `Create a ${duration}-minute walking tour in ${city} based on these themes: ${themes.join(', ')}`,
        },
      ],
    });

    const tourText = response.choices[0].message.content;
    res.json({ tour: tourText });
  } catch (error) {
    console.error('OpenAI error:', error);
    res.status(500).json({ error: 'Failed to generate tour' });
  }
});

// Start the server
app.listen(port, () => {
  console.log(`Server running on http://localhost:${port}`);
});
