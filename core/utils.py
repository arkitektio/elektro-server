from itertools import chain
import strawberry
from typing import Optional, List, Any

# Factor out pagination logic into a separate function
def paginate_querysets(*querysets: Any, offset: int = 0, limit: int = 100,):

    items = []
    remaining_limit = limit  # How many more items we need to fetch
    current_offset = offset  # Start at the initial offset

    # Loop through each queryset
    for qs in querysets:
        qs_count = qs.count()  # Get the total number of items in the current queryset

        # If the current offset is greater than the queryset size, skip this queryset
        if current_offset >= qs_count:
            current_offset -= qs_count
            continue

        # Calculate how many items to fetch from this queryset
        qs_items = qs[current_offset:current_offset + remaining_limit]
        current_offset = 0  # After processing the first queryset, reset offset for the next one

        # Append the fetched items to the results
        items.extend(qs_items)

        # Update the remaining limit after fetching from this queryset
        remaining_limit -= len(qs_items)

        # If we've filled the required limit, break the loop
        if remaining_limit <= 0:
            break

    # Return the paginated items and the total count
    return items
