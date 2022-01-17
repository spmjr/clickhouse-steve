#!/usr/bin/python3

import sys

if __name__ == '__main__':
    arg = int(sys.argv[1])

    for chunk_header in sys.stdin:
        chunk_length = int(chunk_header)
        print(str(chunk_length), end='\n')

        while chunk_length != 0:
            line = sys.stdin.readline()
            chunk_length -= 1
            print("Key " + str(arg) + " " + line, end='')

        sys.stdout.flush()
