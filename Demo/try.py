arr = []
arr2 = []
with open("socres.txt") as txt:
    for line in txt:
        score = int(line)
        arr.append(score)
        print(score)
    print(arr)

    for idx, val in enumerate(arr):
        if val not in arr2:
            count = arr.count(val)
            total = '*' * count
            print(f"{val}: {total}" )
            arr2.append(val)
