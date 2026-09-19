import math

def is_prime(n: int) -> bool:
    if n < 2:
        return False

    if n == 2:
        return True

    if n % 2 == 0:
        return False

    limit = math.isqrt(n)

    divisor = 3

    while divisor <= limit:
        if n % divisor == 0:
            return False

        divisor += 2

    return True

print("enter your number")
n = int(input())
print("1. Check if the number is prime")
print("2. Find next prime number")

x = int(input())
if (x == 1):
    print(is_prime(x))
elif x == 2:
    while True:
        n += 1
        if is_prime(n):
            print(n)
            break
else:
    print("1 or 2")