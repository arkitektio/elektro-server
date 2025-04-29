def compare_dicts(dict_a, dict_b, path=None):
    if path is None:
        path = []
    
    changes = []
    
    keys_a = set(dict_a.keys())
    keys_b = set(dict_b.keys())

    for key in keys_a - keys_b:
        changes.append({
            'type': 'removed',
            'path': path + [key],
            'value_a': dict_a[key],
            'value_b': None
        })

    for key in keys_b - keys_a:
        changes.append({
            'type': 'added',
            'path': path + [key],
            'value_a': None,
            'value_b': dict_b[key]
        })

    for key in keys_a & keys_b:
        val_a = dict_a[key]
        val_b = dict_b[key]

        if isinstance(val_a, dict) and isinstance(val_b, dict):
            changes.extend(compare_dicts(val_a, val_b, path + [key]))
        elif val_a != val_b:
            changes.append({
                'type': 'changed',
                'path': path + [key],
                'value_a': val_a,
                'value_b': val_b
            })
    
    return changes