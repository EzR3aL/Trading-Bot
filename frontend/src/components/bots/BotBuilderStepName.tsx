interface Props {
  name: string
  description: string
  onNameChange: (val: string) => void
  onDescriptionChange: (val: string) => void
  b: Record<string, string>
}

export default function BotBuilderStepName({ name, description, onNameChange, onDescriptionChange, b }: Props) {
  return (
    <div className="space-y-4 max-w-md">
      <div>
        <label htmlFor="bot-name" className="block text-sm text-gray-400 mb-1">{b.name}</label>
        <input
          id="bot-name"
          type="text"
          value={name}
          onChange={e => onNameChange(e.target.value)}
          placeholder={b.namePlaceholder}
          className="filter-select w-full text-sm"
          autoFocus
        />
      </div>
      <div>
        <label htmlFor="bot-description" className="block text-sm text-gray-400 mb-1">{b.description}</label>
        <input
          id="bot-description"
          type="text"
          value={description}
          onChange={e => onDescriptionChange(e.target.value)}
          placeholder={b.descriptionPlaceholder}
          className="filter-select w-full text-sm"
        />
      </div>
    </div>
  )
}
