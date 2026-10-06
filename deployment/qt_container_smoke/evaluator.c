/* Echo transport, with real process-isolation assertions. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
extern unsigned long synthetic_engine(void);
int main(void) {
    if (!synthetic_engine() || getenv("QT_SYNTHETIC_SENTINEL") || getenv("DB_PASSWORD")) return 10;
    FILE *interfaces = fopen("/proc/net/dev", "r");
    if (!interfaces) return 11;
    char line[512]; unsigned int count = 0;
    while (fgets(line, sizeof(line), interfaces)) {
        char *colon = strchr(line, ':');
        if (!colon) continue;
        *colon = 0;
        char *name = line; while (*name == ' ') name++;
        if (strcmp(name, "lo")) return 12;
        count++;
    }
    fclose(interfaces);
    if (count != 1) return 11;
    char path[512] = {0};
    if (readlink("/proc/self/exe", path, sizeof(path)-1) < 0 || !strstr(path, "memfd:")) return 13;
    char buffer[8192]; size_t n, total = 0;
    while ((n = fread(buffer, 1, sizeof(buffer), stdin))) {
        total += n; if (total > 1024*1024) return 14;
        if (fwrite(buffer, 1, n, stdout) != n) return 15;
    }
    return ferror(stdin) ? 16 : 0;
}
