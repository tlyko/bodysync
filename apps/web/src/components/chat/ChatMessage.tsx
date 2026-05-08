import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage as ChatMessageType, UsedRecipe } from '../../types';
import { RecipeCard } from './RecipeCard';

type Props = {
  message: ChatMessageType;
  onRecipeClick: (recipe: UsedRecipe) => void;
};

export function ChatMessage({ message, onRecipeClick }: Props) {
  if (message.role === 'user') {
    return (
      <div className="message-row user">
        <div className="message-bubble user">{message.content}</div>
      </div>
    );
  }

  // assistant
  return (
    <div className="message-row assistant">
      <div className="message-bubble assistant">
        <div className="message-markdown">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        </div>
        {message.used_recipes.length > 0 && (
          <div className="recipe-cards-grid">
            {message.used_recipes.map((r) => (
              <RecipeCard key={r.slug} recipe={r} onClick={() => onRecipeClick(r)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
