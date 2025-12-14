# Frontend Implementation Prompt for v2/words-explanation API Event Streaming

## Context

You are implementing the frontend event handling for the `v2/words-explanation` API endpoint in a Chrome extension. The API streams Server-Sent Events (SSE) with a specific format that needs to be parsed and displayed incrementally in the UI.

## API Response Format

The API endpoint `/api/v2/words-explanation` returns Server-Sent Events where each event contains a `raw_response` string in the following format:

```
[[[WORD_MEANING]]]:{{meaning text}}[[[EXAMPLES]]]:{{[[ITEM]]{{example sentence 1}}[[ITEM]]{{example sentence 2}}}}
```

### Format Details:
- `[[[WORD_MEANING]]]` - Marker indicating the start of word meaning section
- `{{meaning text}}` - The actual meaning text (content between `[[[WORD_MEANING]]]:` and `[[[EXAMPLES]]]`)
- `[[[EXAMPLES]]]` - Marker indicating the start of examples section
- `[[ITEM]]` - Marker indicating the start of each example sentence
- `{{example sentence}}` - The actual example sentence (content between `[[ITEM]]` markers)

### Example Complete Response:
```
[[[WORD_MEANING]]]:{{A word that means something important}}[[[EXAMPLES]]]:{{[[ITEM]]{{This is the first example sentence.}}[[ITEM]]{{This is the second example sentence.}}}}
```

## Current Implementation

The backend API (`app/routes/v2_api.py`) streams the `raw_response` directly as SSE events:
- Each event is in format: `data: {raw_response_string}\n\n`
- The `raw_response` is a plain string (not JSON) containing the formatted response with markers
- Multiple words can be streamed concurrently

The frontend `ApiService.explainWords()` method (in `/Users/Subhram/my-projects/comp/core/services/ApiService.js`) already parses these markers and emits structured events:
- `word_meaning_start` - When `[[[WORD_MEANING]]]` is detected
- `word_meaning_chunk` - For each chunk of meaning text
- `examples_start` - When `[[[EXAMPLES]]]` is detected
- `example_item_start` - When `[[ITEM]]` is detected
- `example_item_chunk` - For each chunk of example text
- `example_item_complete` - When an example is complete (next `[[ITEM]]` or end of stream)

## Required Frontend Behavior

The frontend code in `/Users/Subhram/my-projects/comp/entrypoints/content.js` already has event handlers, but you need to ensure they work correctly according to this specification:

### 1. When `[[[WORD_MEANING]]]` is received:
   - **Immediately show the word-meaning modal/popup**
   - Display subsequent meaning chunks in the meaning component as they arrive
   - The modal should appear as soon as this marker is detected, even if the meaning text is still streaming

### 2. When `[[[EXAMPLES]]]` is received:
   - **Show a purple horizontal divider line**
   - **Display "Examples" heading** (in purple color)
   - This should appear in the same modal/popup that's already showing the meaning

### 3. When `[[ITEM]]` is received:
   - **Show a purple bullet point** (bullet pointer)
   - **Start displaying the example sentence** incrementally as chunks arrive
   - Continue accumulating text until the next `[[ITEM]]` marker or end of stream

### 4. Continue processing:
   - Keep processing events until the stream completes (`[DONE]` event)
   - Each new `[[ITEM]]` starts a new example with a new bullet point
   - All examples should appear in the same modal/popup

## Implementation Details

### Current Event Handler Location
The event handlers are in `/Users/Subhram/my-projects/comp/entrypoints/content.js` around line 27300-27550, specifically in the `onEvent` callback of `ApiService.explainWords()`.

### Key Functions to Use/Implement:
1. **WordSelector.createWordPopupIncremental()** - Creates the modal/popup for displaying word meaning
2. **WordSelector.updateWordPopupMeaning()** - Updates the meaning section incrementally
3. **WordSelector.showExamplesSection()** - Shows the examples section with divider and heading
4. **WordSelector.updateCurrentExample()** - Updates the current example being streamed
5. **WordSelector.appendExampleItem()** - Appends a completed example with bullet point

### Event Flow:
```
SSE Event Received
  ↓
ApiService.parseRawResponse() detects markers
  ↓
Emits structured events (word_meaning_start, examples_start, etc.)
  ↓
onEvent callback in content.js receives structured event
  ↓
UI updates based on event type
```

### State Management:
The code uses `incrementalStates` Map (keyed by `textStartIndex`) to track:
- Current word being processed
- Accumulated meaning text
- Current example being built
- Completed examples array
- Popup element reference
- Flags: `meaningStarted`, `examplesStarted`

## UI Components (You don't need to implement these, they exist)

- **Word Meaning Modal**: A popup that displays word meaning and examples
- **Meaning Component**: Section within the modal that shows the word meaning
- **Purple Divider**: Horizontal line in purple color
- **Examples Heading**: "Examples" text in purple color
- **Purple Bullet Points**: Bullet indicators in purple color for each example
- **Example Sentences**: The actual example text displayed under each bullet

## Testing Checklist

1. ✅ Modal appears immediately when `[[[WORD_MEANING]]]` is received
2. ✅ Meaning text streams incrementally in the meaning component
3. ✅ Purple divider and "Examples" heading appear when `[[[EXAMPLES]]]` is received
4. ✅ Purple bullet point appears when `[[ITEM]]` is received
5. ✅ Example text streams incrementally under the bullet point
6. ✅ Next `[[ITEM]]` creates a new bullet point and starts new example
7. ✅ All examples appear in the same modal
8. ✅ Works correctly for multiple words streamed concurrently

## Notes

- The parsing logic in `ApiService.explainWords()` already handles the marker detection and emits structured events
- Your task is to ensure the UI handlers in `content.js` correctly respond to these events
- The UI components (modal, divider, bullets) already exist - you just need to wire up the event handlers correctly
- Pay attention to the state management to handle concurrent word streams correctly
- The purple color should be consistent with the existing design system

## Files to Modify

1. `/Users/Subhram/my-projects/comp/entrypoints/content.js` - Event handlers in `ButtonPanel.handleMagicMeaning()` method, specifically the `onEvent` callback around lines 27300-27550

## Reference Implementation

The current implementation already has most of the logic in place. Review the event handlers for:
- `word_meaning_start` (line ~27353)
- `word_meaning_chunk` (line ~27402)
- `examples_start` (line ~27415)
- `example_item_start` (line ~27425)
- `example_item_chunk` (line ~27431)
- `example_item_complete` (line ~27441)

Ensure these handlers correctly implement the behavior described above.



