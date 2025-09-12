# https://gist.github.com/radleta/0b337a2b14f761951cf2aab0578512b9
# https://stackoverflow.com/questions/75752274/rsync-for-windows-that-runs-with-git-for-windows-mingw-tools

curl -L https://repo.msys2.org/msys/x86_64/rsync-3.4.1-1-x86_64.pkg.tar.zst --ssl-no-revoke --output xxx
tar -I zstd -xvf xxx
cp usr/bin/rsync.exe 'c:\etc\Git\usr\bin\'
rm -r * .*

curl -L https://repo.msys2.org/msys/x86_64/libzstd-1.5.7-1-x86_64.pkg.tar.zst --ssl-no-revoke --output xxx
tar -I zstd -xvf xxx
cp usr/bin/msys-zstd-1.dll 'c:\etc\Git\usr\bin\'
rm -r * .*

curl -L https://repo.msys2.org/msys/x86_64/libxxhash-0.8.3-1-x86_64.pkg.tar.zst --ssl-no-revoke --output xxx
tar -I zstd -xvf xxx
cp usr/bin/msys-xxhash-0.dll 'c:\etc\Git\usr\bin\'
rm -r * .*

curl -L https://repo.msys2.org/msys/x86_64/liblz4-1.10.1-1-x86_64.pkg.tar.zst --ssl-no-revoke --output xxx
tar -I zstd -xvf xxx
cp usr/bin/msys-lz4-1.dll 'c:\etc\Git\usr\bin\'
rm -r * .*

curl -L https://repo.msys2.org/msys/x86_64/libopenssl-3.5.2-1-x86_64.pkg.tar.zst --ssl-no-revoke --output xxx
tar -I zstd -xvf xxx
cp usr/bin/msys-crypto-3.dll 'c:\etc\Git\usr\bin\'
rm -r * .*

rsync -avz /d/UPRPRC/scripts/dlcache_doc root@127.0.0.1:/mnt/d/UPRPRC/scripts