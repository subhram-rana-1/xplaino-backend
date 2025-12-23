#!/usr/bin/env python3
"""Test the batching logic for translation API."""

from typing import List


class TextItem:
    """Mock text item class."""
    def __init__(self, id: str, text: str):
        self.id = id
        self.text = text
    
    def __repr__(self):
        return f"TextItem(id='{self.id}', text='{self.text[:30]}...', len={len(self.text)})"


def create_batches(text_items: List[TextItem]) -> List[List[TextItem]]:
    """Create batches based on text length (200 char threshold)."""
    batches = []
    current_batch = []
    current_length = 0
    
    for text_item in text_items:
        text_length = len(text_item.text)
        
        # If single item > 200, send it alone
        if text_length > 200:
            # Finalize current batch if any
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_length = 0
            # Add single item as its own batch
            batches.append([text_item])
        else:
            # Add to current batch
            current_batch.append(text_item)
            current_length += text_length
            
            # If total exceeds 200, finalize batch
            if current_length > 200:
                batches.append(current_batch)
                current_batch = []
                current_length = 0
    
    # Don't forget remaining items
    if current_batch:
        batches.append(current_batch)
    
    return batches


def print_batches(batches: List[List[TextItem]]):
    """Print batch information."""
    print(f"\nTotal batches: {len(batches)}")
    for i, batch in enumerate(batches):
        total_chars = sum(len(item.text) for item in batch)
        print(f"\nBatch {i+1}: {len(batch)} items, {total_chars} total chars")
        for item in batch:
            print(f"  - {item.id}: {len(item.text)} chars")


def test_case_1():
    """Test case: All short texts that fit in batches."""
    print("=" * 80)
    print("TEST CASE 1: All short texts (should create batches)")
    print("=" * 80)
    
    items = [
        TextItem("text-1", "Hello" * 20),  # 100 chars
        TextItem("text-2", "World" * 20),  # 100 chars
        TextItem("text-3", "Test" * 15),   # 60 chars
        TextItem("text-4", "API" * 20),    # 60 chars
    ]
    
    batches = create_batches(items)
    print_batches(batches)
    
    # Expected: 2 batches
    # Batch 1: text-1 (100) + text-2 (100) = 200, next would exceed
    # Batch 2: text-3 (60) + text-4 (60) = 120
    assert len(batches) == 2, f"Expected 2 batches, got {len(batches)}"
    assert len(batches[0]) == 2, f"Expected batch 1 to have 2 items"
    assert len(batches[1]) == 2, f"Expected batch 2 to have 2 items"
    print("✓ Test case 1 passed!")


def test_case_2():
    """Test case: Mix of long and short texts."""
    print("\n" + "=" * 80)
    print("TEST CASE 2: Mix of long (>200) and short texts")
    print("=" * 80)
    
    items = [
        TextItem("text-1", "Short" * 15),      # 75 chars
        TextItem("text-2", "Long" * 100),      # 400 chars - should be alone
        TextItem("text-3", "Medium" * 20),     # 120 chars
        TextItem("text-4", "Another" * 50),    # 350 chars - should be alone
        TextItem("text-5", "Small" * 10),      # 50 chars
    ]
    
    batches = create_batches(items)
    print_batches(batches)
    
    # Expected: 4 batches
    # Batch 1: text-1 (75)
    # Batch 2: text-2 (400) alone
    # Batch 3: text-3 (120)
    # Batch 4: text-4 (350) alone
    # Batch 5: text-5 (50)
    assert len(batches) == 5, f"Expected 5 batches, got {len(batches)}"
    assert len(batches[0]) == 1, f"Expected batch 1 to have 1 item"
    assert len(batches[1]) == 1, f"Expected batch 2 to have 1 item (long text)"
    assert batches[1][0].id == "text-2", "Expected text-2 to be alone"
    print("✓ Test case 2 passed!")


def test_case_3():
    """Test case: Exactly at threshold."""
    print("\n" + "=" * 80)
    print("TEST CASE 3: Texts that exactly hit threshold")
    print("=" * 80)
    
    items = [
        TextItem("text-1", "A" * 100),   # 100 chars
        TextItem("text-2", "B" * 100),   # 100 chars
        TextItem("text-3", "C" * 50),    # 50 chars - total would be 250, exceeds
        TextItem("text-4", "D" * 200),   # 200 chars - exactly at threshold but single item
    ]
    
    batches = create_batches(items)
    print_batches(batches)
    
    # Expected: 3 batches
    # Batch 1: text-1 (100) + text-2 (100) = 200
    # Batch 2: text-3 (50)
    # Batch 3: text-4 (200) - not >200, so goes in batch
    assert len(batches) == 3, f"Expected 3 batches, got {len(batches)}"
    print("✓ Test case 3 passed!")


def test_case_4():
    """Test case: Single item."""
    print("\n" + "=" * 80)
    print("TEST CASE 4: Single text item")
    print("=" * 80)
    
    items = [
        TextItem("text-1", "Single" * 30),  # 180 chars
    ]
    
    batches = create_batches(items)
    print_batches(batches)
    
    assert len(batches) == 1, f"Expected 1 batch, got {len(batches)}"
    assert len(batches[0]) == 1, f"Expected batch to have 1 item"
    print("✓ Test case 4 passed!")


def test_case_5():
    """Test case: Many tiny texts."""
    print("\n" + "=" * 80)
    print("TEST CASE 5: Many tiny texts (should batch efficiently)")
    print("=" * 80)
    
    items = [
        TextItem(f"text-{i}", "Hi" * 10)  # 20 chars each
        for i in range(20)  # 20 items
    ]
    
    batches = create_batches(items)
    print_batches(batches)
    
    # Expected: With 20 chars each:
    # Each batch can fit 10 items (200 chars), 11th would exceed
    # 20 items / 10 per batch = 2 batches
    assert len(batches) == 2, f"Expected 2 batches, got {len(batches)}"
    assert len(batches[0]) == 10, f"Expected batch 1 to have 10 items"
    assert len(batches[1]) == 10, f"Expected batch 2 to have 10 items"
    print("✓ Test case 5 passed!")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("TRANSLATION BATCHING LOGIC TEST")
    print("=" * 80)
    
    try:
        test_case_1()
        test_case_2()
        test_case_3()
        test_case_4()
        test_case_5()
        
        print("\n" + "=" * 80)
        print("✓ ALL TESTS PASSED!")
        print("=" * 80 + "\n")
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}\n")
        exit(1)
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}\n")
        exit(1)

