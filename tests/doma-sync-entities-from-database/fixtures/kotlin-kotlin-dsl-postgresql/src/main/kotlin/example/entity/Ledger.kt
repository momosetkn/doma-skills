package example.entity

import org.seasar.doma.Column
import org.seasar.doma.Entity
import org.seasar.doma.Id
import org.seasar.doma.Metamodel
import org.seasar.doma.Table

@Entity(immutable = true, metamodel = Metamodel())
@Table(schema = "public", name = "ledger")
// HANDWRITTEN-BEGIN:ledger-data-class
data class Ledger(
    @Id
    @Column(name = "ledger_id")
    val ledgerId: Long,
)
// HANDWRITTEN-END:ledger-data-class
